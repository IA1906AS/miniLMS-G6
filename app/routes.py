import csv
import io
import re
import secrets
from pathlib import Path
from uuid import uuid4

import bcrypt
from flask import (
    Response,
    current_app,
    g,
    jsonify,
    request,
    send_file,
    send_from_directory,
)
from werkzeug.utils import secure_filename

from audit import log_event
from app import files, services
from app.auth import (
    _DUMMY_HASH,
    _failures,
    _is_locked,
    _record_failure,
    create_token,
    me,
    revoke_token,
)
from app.errors import (
    AccountLocked,
    EmailExists,
    InvalidCredentials,
    InvalidCurrentPassword,
    ValidationError,
)
from app.guards import ExportBusy, require_role


def render_grade_csv(rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("studentId", "score"))
    for row in rows:
        writer.writerow((row["studentId"], row["score"]))
    return output.getvalue()


# ponytail: OTP không có giới hạn gửi/lần (lab); thêm rate-limit nếu lên prod
RESET_OTP_TTL_SECONDS = 300
_DUMMY_OTP_HASH = bcrypt.hashpw(b"00000000", bcrypt.gensalt(rounds=10))


def register_routes(app):
    """Register P4 routes; P1 app factory calls this once after Store setup."""

    @app.post("/auth/login")
    def login():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or "email" not in data or "password" not in data:
            raise InvalidCredentials()

        email = data["email"] if isinstance(data["email"], str) else ""
        password = data["password"]
        if _is_locked(email):
            raise AccountLocked()

        store = current_app.extensions["store"]
        user = store.get_user_by_email(email)
        if user is not None and user.get("locked"):
            raise AccountLocked()
        pw_hash = store.get_password_hash_by_email(email) or _DUMMY_HASH
        ok = isinstance(password, str) and bcrypt.checkpw(password.encode(), pw_hash)
        if user is None or not ok:
            _record_failure(email)
            raise InvalidCredentials()

        _failures().pop(email, None)
        log_event(user["id"], "LOGIN", user["email"], "SUCCESS")
        return {
            "accessToken": create_token(user["id"]),
            "expiresIn": int(current_app.config["TOKEN_TTL_SECONDS"]),
        }, 200

    @app.post("/auth/register")
    def register():
        data = request.get_json(silent=True)
        raw_email = data.get("email", "") if isinstance(data, dict) else ""
        email = raw_email.strip().lower() if isinstance(raw_email, str) else ""
        password = data.get("password", "") if isinstance(data, dict) else ""
        confirmation = data.get("passwordConfirmation", "") if isinstance(data, dict) else ""
        valid_email = re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
        if not valid_email or not isinstance(password, str) or len(password) < 8:
            return {"error": "VALIDATION_ERROR"}, 400
        if password != confirmation:
            return {"error": "PASSWORD_MISMATCH"}, 400

        store = current_app.extensions["store"]
        if store.get_user_by_email(email) is not None:
            raise EmailExists()
        user = store.create_user(uuid4().hex, email, password)
        return {"user": user}, 201

    @app.post("/auth/forgot-password")
    def forgot_password():
        data = request.get_json(silent=True)
        email = data.get("email", "") if isinstance(data, dict) else ""
        if not isinstance(email, str) or not email:
            raise ValidationError()

        store = current_app.extensions["store"]
        otp = f"{secrets.randbelow(10**8):08d}"
        # Email không tồn tại vẫn trả về otp giả — response đồng nhất, không lộ
        # thông tin email nào có tài khoản. Lab: otp "gửi" qua response + stdout.
        user = store.get_user_by_email(email)
        otp_hash = _DUMMY_OTP_HASH
        if user is not None:
            otp_hash = bcrypt.hashpw(otp.encode(), bcrypt.gensalt(rounds=10))
            store.save_reset_otp(email, otp_hash, RESET_OTP_TTL_SECONDS)
        print(f"[LAB OTP] {email} -> {otp}")
        return {"message": "OTP sent to email (lab mode)", "otp": otp}, 200

    @app.post("/auth/reset-password")
    def reset_password():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValidationError()
        email = data.get("email", "")
        otp = data.get("otp", "")
        new_password = data.get("newPassword", "")
        if (
            not isinstance(email, str)
            or not isinstance(otp, str)
            or not isinstance(new_password, str)
            or len(new_password) < 8
        ):
            raise ValidationError()

        store = current_app.extensions["store"]
        user = store.get_user_by_email(email)
        # OTP dùng một lần: sai là xoá ngay, không cho brute-force
        otp_hash = store.get_reset_otp_hash(email) if user else None
        valid = (
            user is not None
            and otp_hash is not None
            and bcrypt.checkpw(otp.encode(), otp_hash)
        )
        if not valid:
            if user is not None:
                store.delete_reset_otp(email)
            return {"error": "INVALID_OTP"}, 400

        store.update_password(user["id"], new_password)
        store.delete_reset_otp(email)
        log_event(user["id"], "RESET_PASSWORD", email, "SUCCESS")
        return {"message": "Password updated"}, 200

    @app.get("/me")
    def current_user():
        return me()

    @app.put("/me")
    def update_me():
        result = services.update_profile(g.actor, request.get_json(silent=True))
        return jsonify(result), 200

    @app.post("/me/avatar")
    def upload_avatar():
        storage = request.files.get("avatar")
        if storage is None:
            raise ValidationError()
        upload_dir = current_app.config["UPLOAD_DIR"]
        old = g.actor.get("avatar_path")
        stored, _original, _size = files.save_upload(
            upload_dir,
            storage,
            "avatars",
            allowed_extensions=files.ALLOWED_IMAGE_EXTENSIONS,
            max_bytes=files.MAX_AVATAR_BYTES,
        )
        result = services.set_avatar(g.actor, stored)
        if old:
            files.delete_upload(upload_dir, "avatars", old)
        return jsonify(result), 200

    @app.get("/files/avatars/<name>")
    def avatar_file(name):
        return send_from_directory(
            Path(current_app.config["UPLOAD_DIR"]) / "avatars", name
        )

    @app.post("/auth/change-password")
    def change_password():
        data = request.get_json(silent=True)
        current_pw = data.get("currentPassword", "") if isinstance(data, dict) else ""
        new_pw = data.get("newPassword", "") if isinstance(data, dict) else ""
        if (
            not isinstance(current_pw, str)
            or not isinstance(new_pw, str)
            or len(new_pw) < 8
        ):
            raise ValidationError()

        store = current_app.extensions["store"]
        pw_hash = store.get_password_hash_by_email(g.actor["email"])
        if pw_hash is None or not bcrypt.checkpw(current_pw.encode(), pw_hash):
            raise InvalidCurrentPassword()

        store.update_password(g.actor["id"], new_pw)
        revoke_token(g.token_payload)
        log_event(g.actor["id"], "CHANGE_PASSWORD", g.actor["id"], "SUCCESS")
        return {"message": "Password updated"}, 200

    @app.post("/auth/logout")
    def logout():
        revoke_token(getattr(g, "token_payload", {}))
        return {"message": "Logged out"}, 200

    @app.get("/members")
    def members():
        course_id = request.args.get("courseId")
        rows = services.list_members(g.actor, course_id)
        return jsonify(rows), 200

    @app.get("/courses/<course_id>/grades")
    @require_role("ADMIN", "INSTRUCTOR", "STUDENT")
    def get_course_grades(course_id):
        store = current_app.extensions["store"]
        v_param = request.args.get("version")
        include_version = v_param.lower() in ("1", "true") if v_param else None
        rows = services.get_grades(
            g.actor, course_id, include_version=include_version, store=store
        )
        return jsonify(rows), 200

    @app.get("/courses/<course_id>/grades/<student_id>")
    @require_role("ADMIN", "INSTRUCTOR", "STUDENT")
    def get_course_grade(course_id, student_id):
        store = current_app.extensions["store"]
        row = services.get_grade(g.actor, course_id, student_id, store=store)
        return jsonify(row), 200

    @app.get("/courses/<course_id>/grades/export")
    @require_role("ADMIN", "INSTRUCTOR", "STUDENT")
    def export_course_grades(course_id):
        try:
            with current_app.extensions["grade_export_bulkhead"].slot():
                rows = services.get_grades(
                    g.actor, course_id, store=current_app.extensions["store"]
                )
                content = render_grade_csv(rows)
                filename = f"grades-{secure_filename(course_id) or 'course'}.csv"
                return Response(
                    content,
                    mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                )
        except ExportBusy:
            return {"error": "EXPORT_BUSY"}, 503

    @app.put("/courses/<course_id>/grades/<student_id>")
    @require_role("ADMIN", "INSTRUCTOR", "STUDENT")
    def put_course_grade(course_id, student_id):
        store = current_app.extensions["store"]
        body = request.get_json(silent=True)
        old_score, new_score, new_version = services.update_grade(
            g.actor,
            course_id,
            student_id,
            body,
            store=store,
        )
        log_event(
            g.actor["id"],
            "UPDATE_GRADE",
            f"{course_id}/{student_id}",
            "SUCCESS",
            oldScore=old_score,
            newScore=new_score,
        )
        resp = {
            "courseId": course_id,
            "studentId": student_id,
            "score": new_score,
        }
        if isinstance(body, dict) and "version" in body:
            resp["version"] = new_version
        return jsonify(resp), 200

    @app.post("/courses/<course_id>/quizzes/<quiz_id>/attempts")
    @require_role("STUDENT")
    def start_quiz_attempt(course_id, quiz_id):
        store = current_app.extensions["store"]
        attempt = services.start_attempt(
            g.actor,
            course_id,
            quiz_id,
            deadline_minutes=int(current_app.config["QUIZ_DEADLINE_MINUTES"]),
            store=store,
        )
        return jsonify(attempt), 201

    @app.get("/courses/<course_id>/quizzes/<quiz_id>/attempts")
    @require_role("ADMIN", "INSTRUCTOR", "STUDENT")
    def get_quiz_attempts(course_id, quiz_id):
        store = current_app.extensions["store"]
        rows = services.get_attempts(
            g.actor,
            course_id,
            quiz_id,
            student_id=request.args.get("studentId"),
            store=store,
        )
        return jsonify(rows), 200

    @app.put("/courses/<course_id>/quizzes/<quiz_id>/attempts/answers")
    @require_role("STUDENT")
    def save_quiz_answers(course_id, quiz_id):
        store = current_app.extensions["store"]
        body = request.get_json(silent=True)
        answers = body.get("answers") if isinstance(body, dict) else None
        attempt = services.save_answers(
            g.actor, course_id, quiz_id, answers, store=store
        )
        return jsonify(attempt), 200

    @app.post("/courses/<course_id>/quizzes/<quiz_id>/attempts/submit")
    @require_role("STUDENT")
    def submit_quiz_attempt(course_id, quiz_id):
        store = current_app.extensions["store"]
        body = request.get_json(silent=True)
        answers = body.get("answers") if isinstance(body, dict) else None
        attempt = services.submit_attempt(
            g.actor, course_id, quiz_id, answers, store=store
        )
        log_event(
            g.actor["id"],
            "SUBMIT_ATTEMPT",
            f"{course_id}/{quiz_id}",
            "SUCCESS",
            state=attempt["state"],
        )
        return jsonify(attempt), 200

    @app.post(
        "/courses/<course_id>/quizzes/<quiz_id>/attempts/<student_id>/grade"
    )
    @require_role("INSTRUCTOR")
    def grade_quiz_attempt(course_id, quiz_id, student_id):
        store = current_app.extensions["store"]
        body = request.get_json(silent=True)
        score = body.get("score") if isinstance(body, dict) else None
        attempt = services.grade_attempt(
            g.actor, course_id, quiz_id, student_id, score, store=store
        )
        log_event(
            g.actor["id"],
            "GRADE_ATTEMPT",
            f"{course_id}/{quiz_id}/{student_id}",
            "SUCCESS",
            score=attempt["score"],
        )
        return jsonify(attempt), 200

    # ── Courses ─────────────────────────────────────────────────────────

    @app.get("/api/courses")
    def api_courses():
        store = current_app.extensions["store"]
        rows = services.list_courses(
            g.actor,
            q=request.args.get("q"),
            instructor_id=request.args.get("instructorId"),
            store=store,
        )
        return jsonify(rows), 200

    @app.post("/courses")
    @require_role("INSTRUCTOR", "ADMIN")
    def create_course():
        store = current_app.extensions["store"]
        course = services.create_course(
            g.actor, request.get_json(silent=True), store=store
        )
        return jsonify(course), 201

    @app.patch("/courses/<course_id>")
    @require_role("INSTRUCTOR", "ADMIN")
    def update_course(course_id):
        store = current_app.extensions["store"]
        course = services.update_course(
            g.actor, course_id, request.get_json(silent=True), store=store
        )
        return jsonify(course), 200

    @app.post("/courses/enroll")
    @require_role("STUDENT")
    def enroll_by_code():
        store = current_app.extensions["store"]
        body = request.get_json(silent=True)
        code = body.get("code") if isinstance(body, dict) else None
        enrollment = services.enroll_by_code(g.actor, code, store=store)
        log_event(g.actor["id"], "ENROLL", enrollment["courseId"], "SUCCESS")
        return jsonify(enrollment), 201

    @app.post("/courses/<course_id>/students")
    @require_role("INSTRUCTOR", "ADMIN")
    def add_course_student(course_id):
        store = current_app.extensions["store"]
        body = request.get_json(silent=True)
        student_id = body.get("studentId") if isinstance(body, dict) else None
        if not isinstance(student_id, str) or not student_id.strip():
            raise ValidationError()
        enrollment = services.add_student(
            g.actor, course_id, student_id.strip(), store=store
        )
        log_event(g.actor["id"], "ENROLL", f"{course_id}/{student_id}", "SUCCESS")
        return jsonify(enrollment), 201

    # ── Materials ───────────────────────────────────────────────────────

    @app.post("/courses/<course_id>/materials")
    @require_role("INSTRUCTOR", "ADMIN")
    def upload_material(course_id):
        storage = request.files.get("file")
        if storage is None:
            raise ValidationError()
        stored, original, size = files.save_upload(
            current_app.config["UPLOAD_DIR"], storage, "materials"
        )
        store = current_app.extensions["store"]
        try:
            material = services.create_material(
                g.actor, course_id, stored, original, size, store=store
            )
        except Exception:
            files.delete_upload(
                current_app.config["UPLOAD_DIR"], "materials", stored
            )
            raise
        return jsonify(material), 201

    @app.get("/courses/<course_id>/materials")
    def list_course_materials(course_id):
        store = current_app.extensions["store"]
        rows = services.list_materials(g.actor, course_id, store=store)
        return jsonify(rows), 200

    @app.get("/materials/<material_id>/download")
    def download_material(material_id):
        store = current_app.extensions["store"]
        material = services.get_material_file(g.actor, material_id, store=store)
        path = files.upload_path(
            current_app.config["UPLOAD_DIR"], "materials", material["stored_name"]
        )
        return send_file(path, as_attachment=True, download_name=material["original_name"])

    @app.delete("/materials/<material_id>")
    @require_role("INSTRUCTOR", "ADMIN")
    def delete_material(material_id):
        store = current_app.extensions["store"]
        removed = services.delete_material(g.actor, material_id, store=store)
        files.delete_upload(
            current_app.config["UPLOAD_DIR"], "materials", removed["stored_name"]
        )
        return {"message": "Deleted"}, 200

    # ── Assignments and submissions ─────────────────────────────────────

    @app.post("/courses/<course_id>/assignments")
    @require_role("INSTRUCTOR", "ADMIN")
    def create_assignment(course_id):
        store = current_app.extensions["store"]
        assignment = services.create_assignment(
            g.actor, course_id, request.get_json(silent=True), store=store
        )
        return jsonify(assignment), 201

    @app.get("/courses/<course_id>/assignments")
    def list_assignments(course_id):
        store = current_app.extensions["store"]
        rows = services.list_assignments(g.actor, course_id, store=store)
        return jsonify(rows), 200

    @app.post(
        "/courses/<course_id>/assignments/<assignment_id>/submissions"
    )
    @require_role("STUDENT")
    def submit_assignment(course_id, assignment_id):
        storage = request.files.get("file")
        if storage is None:
            raise ValidationError()
        stored, original, _size = files.save_upload(
            current_app.config["UPLOAD_DIR"], storage, "submissions"
        )
        store = current_app.extensions["store"]
        try:
            submission = services.submit_assignment(
                g.actor, course_id, assignment_id, stored, original, store=store
            )
        except Exception:
            files.delete_upload(
                current_app.config["UPLOAD_DIR"], "submissions", stored
            )
            raise
        return jsonify(submission), 201

    @app.get(
        "/courses/<course_id>/assignments/<assignment_id>/submissions"
    )
    def list_submissions(course_id, assignment_id):
        store = current_app.extensions["store"]
        rows = services.list_submissions(
            g.actor, course_id, assignment_id, store=store
        )
        return jsonify(rows), 200

    @app.get("/assignments/submissions/<submission_id>/download")
    def download_submission(submission_id):
        store = current_app.extensions["store"]
        submission = services.get_submission_file(
            g.actor, submission_id, store=store
        )
        path = files.upload_path(
            current_app.config["UPLOAD_DIR"],
            "submissions",
            submission["stored_name"],
        )
        return send_file(
            path, as_attachment=True, download_name=submission["original_name"]
        )

    @app.post(
        "/courses/<course_id>/assignments/<assignment_id>/submissions"
        "/<student_id>/grade"
    )
    @require_role("INSTRUCTOR", "ADMIN")
    def grade_submission(course_id, assignment_id, student_id):
        store = current_app.extensions["store"]
        body = request.get_json(silent=True)
        score = body.get("score") if isinstance(body, dict) else None
        feedback = body.get("feedback") if isinstance(body, dict) else None
        submission = services.grade_submission(
            g.actor, course_id, assignment_id, student_id, score, feedback, store=store
        )
        log_event(
            g.actor["id"],
            "GRADE_SUBMISSION",
            f"{course_id}/{assignment_id}/{student_id}",
            "SUCCESS",
            score=submission["score"],
        )
        return jsonify(submission), 200

    # ── Quizzes ─────────────────────────────────────────────────────────

    @app.post("/courses/<course_id>/quizzes")
    @require_role("INSTRUCTOR", "ADMIN")
    def create_quiz(course_id):
        store = current_app.extensions["store"]
        quiz = services.create_quiz(
            g.actor, course_id, request.get_json(silent=True), store=store
        )
        return jsonify(quiz), 201

    @app.get("/courses/<course_id>/quizzes")
    def list_quizzes(course_id):
        store = current_app.extensions["store"]
        rows = services.list_quizzes(g.actor, course_id, store=store)
        return jsonify(rows), 200

    @app.get("/courses/<course_id>/quizzes/<quiz_id>")
    def get_quiz(course_id, quiz_id):
        store = current_app.extensions["store"]
        quiz = services.get_quiz(g.actor, course_id, quiz_id, store=store)
        return jsonify(quiz), 200
