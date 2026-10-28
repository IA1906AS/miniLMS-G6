import re
import secrets

import bcrypt
from flask import current_app, g, jsonify, render_template, request

from audit import log_event
from app import services
from app.auth import (
    _DUMMY_HASH,
    _failures,
    _is_locked,
    _record_failure,
    create_token,
    me,
)
from app.errors import AccountLocked, InvalidCredentials, ValidationError
from app.guards import require_role

# ponytail: OTP không có giới hạn gửi/lần (lab); thêm rate-limit nếu lên prod
RESET_OTP_TTL_SECONDS = 300
_DUMMY_OTP_HASH = bcrypt.hashpw(b"00000000", bcrypt.gensalt(rounds=10))


def register_routes(app):
    """Register P4 routes; P1 app factory calls this once after Store setup."""

    @app.get("/login")
    def login_page():
        return render_template("login.html")

    @app.get("/register")
    def register_page():
        return render_template("register.html")

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
        pw_hash = store.get_password_hash_by_email(email) or _DUMMY_HASH
        ok = isinstance(password, str) and bcrypt.checkpw(password.encode(), pw_hash)
        if user is None or not ok:
            _record_failure(email)
            raise InvalidCredentials()

        _failures().pop(email, None)
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
            return {"error": "EMAIL_ALREADY_EXISTS"}, 409
        return {"user": store.create_user(email, password)}, 201

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

    @app.get("/courses/<course_id>/grades")
    @require_role("ADMIN", "INSTRUCTOR", "STUDENT")
    def get_course_grades(course_id):
        store = current_app.extensions["store"]
        rows = services.get_grades(g.actor, course_id, store=store)
        return jsonify(rows), 200

    @app.put("/courses/<course_id>/grades/<student_id>")
    @require_role("ADMIN", "INSTRUCTOR", "STUDENT")
    def put_course_grade(course_id, student_id):
        store = current_app.extensions["store"]
        old_score, new_score = services.update_grade(
            g.actor,
            course_id,
            student_id,
            request.get_json(silent=True),
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
        return jsonify(
            courseId=course_id,
            studentId=student_id,
            score=new_score,
        ), 200
