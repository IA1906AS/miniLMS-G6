import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import attempt_sm
from app.errors import Forbidden, NotFound, ValidationError
from app.schemas import validate_answers, validate_grade_body, validate_score

_store = None


def configure_store(store):
    """Set the P1 Store instance for direct service calls."""
    global _store
    _store = store


def _get_store(store=None):
    current = store or _store
    if current is None:
        raise RuntimeError("service store is not configured")
    return current


def _course(store, course_id):
    course = store.get_course(course_id)
    if course is None:
        raise NotFound()
    return course


def get_grades(actor, course_id, *, include_version=None, store=None):
    """Return only grades visible to actor; no Flask dependency."""
    current = _get_store(store)
    course = _course(current, course_id)
    rows = current.get_grades(course_id, include_version=True)

    if actor["role"] == "ADMIN":
        visible = rows
    elif actor["role"] == "INSTRUCTOR":
        if not current.is_instructor_of(actor["id"], course["id"]):
            raise Forbidden()
        visible = rows
    else:
        visible = [row for row in rows if row["studentId"] == actor["id"]]
        if not visible:
            raise Forbidden()

    with_version = (
        include_version
        if include_version is not None
        else (actor["role"] in ("ADMIN", "INSTRUCTOR"))
    )

    if with_version:
        return [
            {
                "studentId": row["studentId"],
                "score": row["score"],
                "version": row.get("version", 1),
            }
            for row in visible
        ]
    return [{"studentId": row["studentId"], "score": row["score"]} for row in visible]


def get_grade(actor, course_id, student_id, *, store=None):
    """Return grade with version for a specific student, checking object authorization."""
    current = _get_store(store)
    course = _course(current, course_id)

    if actor["role"] == "ADMIN":
        pass
    elif actor["role"] == "INSTRUCTOR":
        if not current.is_instructor_of(actor["id"], course["id"]):
            raise Forbidden()
    else:
        if actor["id"] != student_id:
            raise Forbidden()

    enrollment = current.get_enrollment(course_id, student_id)
    if enrollment is None:
        raise NotFound()

    return {
        "courseId": course_id,
        "studentId": student_id,
        "score": enrollment["score"],
        "version": enrollment.get("version", 1),
    }


def update_grade(actor, course_id, student_id, score, *, version=None, store=None):
    """Update a grade with object authorization and strict validation."""
    current = _get_store(store)
    _course(current, course_id)

    if actor["role"] != "INSTRUCTOR" or not current.is_instructor_of(actor["id"], course_id):
        raise Forbidden()

    req_version = version
    if isinstance(score, dict):
        validated_score, parsed_version = validate_grade_body(score)
        if req_version is None:
            req_version = parsed_version
    else:
        validated_score = validate_score(score)
        if req_version is None:
            raise ValidationError()

    if req_version is None:
        raise ValidationError()

    enrollment = current.get_enrollment(course_id, student_id)
    if enrollment is None:
        raise NotFound()

    old_score = enrollment["score"]
    updated = current.set_score(course_id, student_id, validated_score, req_version)
    if updated is None:
        raise NotFound()

    new_version = updated["version"]
    return old_score, validated_score, new_version


def _require_student_enrolled(store, actor, course_id):
    if actor["role"] != "STUDENT":
        raise Forbidden()
    if store.get_enrollment(course_id, actor["id"]) is None:
        raise Forbidden()


def start_attempt(actor, course_id, quiz_id, *, deadline_minutes, store=None):
    current = _get_store(store)
    _course(current, course_id)
    _require_student_enrolled(current, actor, course_id)
    deadline = datetime.now(timezone.utc) + timedelta(minutes=deadline_minutes)
    return current.start_attempt(course_id, quiz_id, actor["id"], deadline)


def get_attempts(actor, course_id, quiz_id, *, student_id=None, store=None):
    current = _get_store(store)
    _course(current, course_id)

    if actor["role"] == "ADMIN":
        return current.list_attempts(course_id, quiz_id)
    if actor["role"] == "INSTRUCTOR":
        if not current.is_instructor_of(actor["id"], course_id):
            raise Forbidden()
        return current.list_attempts(course_id, quiz_id)

    if student_id and student_id != actor["id"]:
        raise Forbidden()
    row = current.get_attempt(course_id, quiz_id, actor["id"])
    return [row] if row else []


def save_answers(actor, course_id, quiz_id, answers, *, store=None):
    current = _get_store(store)
    _course(current, course_id)
    _require_student_enrolled(current, actor, course_id)
    validated = validate_answers(answers)
    attempt = current.get_attempt(course_id, quiz_id, actor["id"])
    if attempt is None:
        raise NotFound()
    attempt_sm.transition(attempt["state"], attempt_sm.SAVE)
    updated = current.save_answers(
        course_id, quiz_id, actor["id"], validated, from_state=attempt["state"]
    )
    if updated is None:
        raise NotFound()
    return updated


def submit_attempt(actor, course_id, quiz_id, answers, *, store=None):
    current = _get_store(store)
    _course(current, course_id)
    _require_student_enrolled(current, actor, course_id)
    validated = validate_answers(answers)
    attempt = current.get_attempt(course_id, quiz_id, actor["id"])
    if attempt is None:
        raise NotFound()
    to_state = attempt_sm.transition(attempt["state"], attempt_sm.SUBMIT)
    updated = current.submit_attempt(
        course_id,
        quiz_id,
        actor["id"],
        validated,
        from_state=attempt["state"],
        to_state=to_state,
    )
    if updated is None:
        raise NotFound()
    score = _autograde(current, course_id, quiz_id, actor["id"], validated)
    if score is not None:
        updated = dict(updated, score=score)
    return updated


def grade_attempt(actor, course_id, quiz_id, student_id, score, *, store=None):
    current = _get_store(store)
    _course(current, course_id)
    if actor["role"] != "INSTRUCTOR" or not current.is_instructor_of(
        actor["id"], course_id
    ):
        raise Forbidden()
    validated = validate_score(score)
    attempt = current.get_attempt(course_id, quiz_id, student_id)
    if attempt is None:
        raise NotFound()
    to_state = attempt_sm.transition(attempt["state"], attempt_sm.GRADE)
    updated = current.grade_attempt(
        course_id,
        quiz_id,
        student_id,
        validated,
        from_state=attempt["state"],
        to_state=to_state,
    )
    if updated is None:
        raise NotFound()
    return updated


# ------------------------------------------------------------------ #
#  Profile and members                                                 #
# ------------------------------------------------------------------ #


def update_profile(actor, payload, *, store=None):
    current = _get_store(store)
    if not isinstance(payload, dict):
        raise ValidationError()
    full_name = payload.get("fullName", "")
    bio = payload.get("bio", "")
    phone = payload.get("phone", "")
    for value in (full_name, bio, phone):
        if not isinstance(value, str):
            raise ValidationError()
    if len(full_name) > 100 or len(bio) > 500 or len(phone) > 30:
        raise ValidationError()
    cleaned = (full_name.strip(), bio.strip(), phone.strip())
    if not current.update_user_profile(actor["id"], *cleaned):
        raise NotFound()
    return {
        "id": actor["id"],
        "email": actor["email"],
        "role": actor["role"],
        "fullName": cleaned[0],
        "bio": cleaned[1],
        "phone": cleaned[2],
    }


def set_avatar(actor, stored_name, *, store=None):
    current = _get_store(store)
    if not current.set_avatar(actor["id"], stored_name):
        raise NotFound()
    return {"avatarUrl": f"/files/avatars/{stored_name}"}


def list_members(actor, course_id=None, *, store=None):
    current = _get_store(store)
    if course_id is None:
        if actor["role"] != "ADMIN":
            raise Forbidden()
        return current.list_users()
    _course(current, course_id)
    if actor["role"] == "INSTRUCTOR" and not current.is_instructor_of(
        actor["id"], course_id
    ):
        raise Forbidden()
    if actor["role"] == "STUDENT" and current.get_enrollment(
        course_id, actor["id"]
    ) is None:
        raise Forbidden()
    return current.list_course_members(course_id)


# ------------------------------------------------------------------ #
#  Courses                                                             #
# ------------------------------------------------------------------ #


def _course_visible(store, actor, course_id):
    """ADMIN, instructor-of, or enrolled student may read course content."""
    if actor["role"] == "ADMIN":
        return
    if actor["role"] == "INSTRUCTOR":
        if store.is_instructor_of(actor["id"], course_id):
            return
    elif store.get_enrollment(course_id, actor["id"]) is not None:
        return
    raise Forbidden()


def list_courses(actor, q=None, instructor_id=None, *, store=None):
    current = _get_store(store)
    enrolled_of = actor["id"] if actor["role"] == "STUDENT" else None
    if actor["role"] == "INSTRUCTOR":
        instructor_id = actor["id"]
    return current.search_courses(q=q, instructor_id=instructor_id, enrolled_of=enrolled_of)


def _validate_course_fields(payload):
    if not isinstance(payload, dict):
        raise ValidationError()
    title = payload.get("title", "")
    code = payload.get("code", "")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
        raise ValidationError()
    if not isinstance(code, str) or not 1 <= len(code.strip()) <= 20:
        raise ValidationError()
    return title.strip(), code.strip()


def create_course(actor, payload, *, store=None):
    current = _get_store(store)
    if actor["role"] not in ("ADMIN", "INSTRUCTOR"):
        raise Forbidden()
    title, code = _validate_course_fields(payload)
    return current.create_course(title, actor["id"], code)


def update_course(actor, course_id, payload, *, store=None):
    current = _get_store(store)
    _course(current, course_id)
    if actor["role"] != "ADMIN" and not current.is_instructor_of(
        actor["id"], course_id
    ):
        raise Forbidden()
    title, code = _validate_course_fields(payload)
    updated = current.update_course(course_id, title, code)
    if updated is None:
        raise NotFound()
    return updated


def enroll_by_code(actor, code, *, store=None):
    current = _get_store(store)
    if actor["role"] != "STUDENT":
        raise Forbidden()
    if not isinstance(code, str) or not code.strip():
        raise ValidationError()
    course = current.get_course_by_code(code.strip())
    if course is None:
        raise NotFound()
    if current.get_enrollment(course["id"], actor["id"]) is not None:
        raise Conflict("Bạn đã ghi danh khoá học này")
    return current.add_enrollment(course["id"], actor["id"])


def add_student(actor, course_id, student_id, *, store=None):
    current = _get_store(store)
    _course(current, course_id)
    if actor["role"] != "ADMIN" and not current.is_instructor_of(
        actor["id"], course_id
    ):
        raise Forbidden()
    if current.get_user_by_id(student_id) is None:
        raise NotFound()
    if current.get_enrollment(course_id, student_id) is not None:
        raise Conflict("Sinh viên đã ghi danh khoá học này")
    return current.add_enrollment(course_id, student_id)


# ------------------------------------------------------------------ #
#  Materials                                                           #
# ------------------------------------------------------------------ #


def list_materials(actor, course_id, *, store=None):
    current = _get_store(store)
    _course(current, course_id)
    _course_visible(current, actor, course_id)
    return current.list_materials(course_id)


def create_material(actor, course_id, stored_name, original_name, size, *, store=None):
    current = _get_store(store)
    _course(current, course_id)
    if actor["role"] != "ADMIN" and not current.is_instructor_of(
        actor["id"], course_id
    ):
        raise Forbidden()
    return current.create_material(
        course_id, actor["id"], original_name, stored_name, size
    )


def get_material_file(actor, material_id, *, store=None):
    current = _get_store(store)
    material = current.get_material_file(material_id)
    if material is None:
        raise NotFound()
    _course(current, material["course_id"])
    _course_visible(current, actor, material["course_id"])
    return material


def delete_material(actor, material_id, *, store=None):
    current = _get_store(store)
    material = current.get_material_file(material_id)
    if material is None:
        raise NotFound()
    _course(current, material["course_id"])
    allowed = (
        actor["role"] == "ADMIN"
        or material["uploader_id"] == actor["id"]
        or current.is_instructor_of(actor["id"], material["course_id"])
    )
    if not allowed:
        raise Forbidden()
    return current.delete_material(material_id)


# ------------------------------------------------------------------ #
#  Assignments and submissions                                         #
# ------------------------------------------------------------------ #


def _parse_due_at(value):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError()
    try:
        due = datetime.fromisoformat(value.strip())
    except ValueError:
        raise ValidationError() from None
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    if due <= datetime.now(timezone.utc):
        raise ValidationError()
    return due


def create_assignment(actor, course_id, payload, *, store=None):
    current = _get_store(store)
    _course(current, course_id)
    if actor["role"] != "ADMIN" and not current.is_instructor_of(
        actor["id"], course_id
    ):
        raise Forbidden()
    if not isinstance(payload, dict):
        raise ValidationError()
    title = payload.get("title", "")
    description = payload.get("description", "")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
        raise ValidationError()
    if not isinstance(description, str) or len(description) > 2000:
        raise ValidationError()
    due_at = _parse_due_at(payload.get("dueAt"))
    return current.create_assignment(course_id, title.strip(), description, due_at)


def list_assignments(actor, course_id, *, store=None):
    current = _get_store(store)
    _course(current, course_id)
    _course_visible(current, actor, course_id)
    return current.list_assignments(course_id)


def _assignment_of_course(store, course_id, assignment_id):
    assignment = store.get_assignment(assignment_id)
    if assignment is None or assignment["courseId"] != course_id:
        raise NotFound()
    return assignment


def submit_assignment(
    actor, course_id, assignment_id, stored_name, original_name, *, store=None
):
    current = _get_store(store)
    _course(current, course_id)
    _require_student_enrolled(current, actor, course_id)
    _assignment_of_course(current, course_id, assignment_id)
    updated = current.upsert_submission(
        assignment_id, actor["id"], original_name, stored_name
    )
    if updated is None:
        # The guarded INSERT can only fail on the deadline check here.
        raise DeadlinePassed()
    return updated


def list_submissions(actor, course_id, assignment_id, *, store=None):
    current = _get_store(store)
    _course(current, course_id)
    _assignment_of_course(current, course_id, assignment_id)
    if actor["role"] in ("ADMIN", "INSTRUCTOR"):
        if actor["role"] == "INSTRUCTOR" and not current.is_instructor_of(
            actor["id"], course_id
        ):
            raise Forbidden()
        return current.list_submissions(assignment_id)
    _require_student_enrolled(current, actor, course_id)
    return current.list_submissions(assignment_id, student_id=actor["id"])


def get_submission_file(actor, submission_id, *, store=None):
    current = _get_store(store)
    submission = current.get_submission_file(submission_id)
    if submission is None:
        raise NotFound()
    if actor["role"] == "ADMIN":
        return submission
    if actor["role"] == "INSTRUCTOR":
        if current.is_instructor_of(actor["id"], submission["course_id"]):
            return submission
    elif submission["student_id"] == actor["id"]:
        return submission
    raise Forbidden()


def grade_submission(
    actor, course_id, assignment_id, student_id, score, feedback, *, store=None
):
    current = _get_store(store)
    _course(current, course_id)
    _assignment_of_course(current, course_id, assignment_id)
    if actor["role"] != "ADMIN" and not current.is_instructor_of(
        actor["id"], course_id
    ):
        raise Forbidden()
    validated_score = validate_score(score)
    if feedback is None:
        feedback = ""
    if not isinstance(feedback, str) or len(feedback) > 1000:
        raise ValidationError()
    graded = current.grade_submission(
        assignment_id, student_id, validated_score, feedback
    )
    if graded is None:
        raise NotFound()
    return graded


# ------------------------------------------------------------------ #
#  Quizzes, questions, auto-grading                                    #
# ------------------------------------------------------------------ #


def _validate_questions(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 50:
        raise ValidationError()
    questions = []
    for position, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValidationError()
        text = item.get("text", "")
        options = item.get("options", [])
        answer_index = item.get("answerIndex")
        points = item.get("points", 1)
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
            raise ValidationError()
        if (
            not isinstance(options, list)
            or not 2 <= len(options) <= 6
            or not all(isinstance(o, str) and o.strip() for o in options)
        ):
            raise ValidationError()
        if (
            isinstance(answer_index, bool)
            or not isinstance(answer_index, int)
            or not 0 <= answer_index < len(options)
        ):
            raise ValidationError()
        if isinstance(points, bool) or not isinstance(points, int) or not 1 <= points <= 10:
            raise ValidationError()
        questions.append(
            {
                "position": position,
                "text": text.strip(),
                "options": [o.strip() for o in options],
                "answer_key": chr(ord("A") + answer_index),
                "points": points,
            }
        )
    return questions


def create_quiz(actor, course_id, payload, *, store=None):
    current = _get_store(store)
    _course(current, course_id)
    if actor["role"] != "ADMIN" and not current.is_instructor_of(
        actor["id"], course_id
    ):
        raise Forbidden()
    if not isinstance(payload, dict):
        raise ValidationError()
    title = payload.get("title", "")
    time_minutes = payload.get("timeMinutes", 30)
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
        raise ValidationError()
    if isinstance(time_minutes, bool) or not isinstance(time_minutes, int):
        raise ValidationError()
    if not 1 <= time_minutes <= 180:
        raise ValidationError()
    questions = _validate_questions(payload.get("questions"))
    return current.create_quiz(course_id, title.strip(), time_minutes, questions)


def list_quizzes(actor, course_id, *, store=None):
    current = _get_store(store)
    _course(current, course_id)
    _course_visible(current, actor, course_id)
    return current.list_quizzes(course_id)


def get_quiz(actor, course_id, quiz_id, *, store=None):
    current = _get_store(store)
    _course(current, course_id)
    quiz = current.get_quiz(quiz_id)
    if quiz is None or quiz["courseId"] != course_id:
        raise NotFound()
    _course_visible(current, actor, course_id)
    questions = current.list_questions(quiz_id)
    if actor["role"] == "STUDENT":
        questions = [
            {k: v for k, v in q.items() if k != "answerKey"} for q in questions
        ]
    return {**quiz, "questions": questions}


def _autograde(store, course_id, quiz_id, student_id, answers_text):
    """Score submitted answers against the answer key; None if quiz has none."""
    questions = store.list_questions(quiz_id)
    if not questions:
        return None
    submitted = [a.strip().upper() for a in answers_text.split(",")]
    total = sum(q["points"] for q in questions)
    earned = 0
    for index, question in enumerate(questions):
        answer = submitted[index] if index < len(submitted) else ""
        if answer == question["answerKey"]:
            earned += question["points"]
    score = round(10 * earned / total, 1)
    store.set_attempt_score(course_id, quiz_id, student_id, score)
    return score


# ------------------------------------------------------------------ #
#  Forum and announcements                                            #
# ------------------------------------------------------------------ #


def _validate_post_fields(payload, *, title_max=200, body_max=2000):
    if not isinstance(payload, dict):
        raise ValidationError()
    title = payload.get("title", "")
    body = payload.get("body", "")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= title_max:
        raise ValidationError()
    if not isinstance(body, str) or not 1 <= len(body.strip()) <= body_max:
        raise ValidationError()
    return title.strip(), body.strip()


def create_topic(actor, course_id, payload, *, store=None):
    current = _get_store(store)
    _course(current, course_id)
    _course_visible(current, actor, course_id)
    title, body = _validate_post_fields(payload)
    return current.create_topic(course_id, actor["id"], title, body)


def list_topics(actor, course_id, *, store=None):
    current = _get_store(store)
    _course(current, course_id)
    _course_visible(current, actor, course_id)
    return current.list_topics(course_id)


def _own_topic(store, actor, topic_id):
    topic = store.get_topic(topic_id)
    if topic is None:
        raise NotFound()
    # Spec: users may only edit or delete their own content.
    if topic["authorId"] != actor["id"]:
        raise Forbidden()
    return topic


def update_topic(actor, topic_id, payload, *, store=None):
    current = _get_store(store)
    topic = _own_topic(current, actor, topic_id)
    title, body = _validate_post_fields(payload)
    return current.update_topic(topic["id"], title, body)


def delete_topic(actor, topic_id, *, store=None):
    current = _get_store(store)
    topic = _own_topic(current, actor, topic_id)
    current.delete_topic(topic["id"])
    return {"message": "Deleted"}


def _visible_topic(store, actor, topic_id):
    topic = store.get_topic(topic_id)
    if topic is None:
        raise NotFound()
    _course_visible(store, actor, topic["courseId"])
    return topic


def create_comment(actor, topic_id, body, *, store=None):
    current = _get_store(store)
    topic = _visible_topic(current, actor, topic_id)
    if not isinstance(body, str) or not 1 <= len(body.strip()) <= 2000:
        raise ValidationError()
    return current.create_comment(topic["id"], actor["id"], body.strip())


def list_comments(actor, topic_id, *, store=None):
    current = _get_store(store)
    topic = _visible_topic(current, actor, topic_id)
    return current.list_comments(topic["id"])


def _own_comment(store, actor, comment_id):
    comment = store.get_comment(comment_id)
    if comment is None:
        raise NotFound()
    if comment["author_id"] != actor["id"]:
        raise Forbidden()
    return comment


def update_comment(actor, comment_id, body, *, store=None):
    current = _get_store(store)
    comment = _own_comment(current, actor, comment_id)
    if not isinstance(body, str) or not 1 <= len(body.strip()) <= 2000:
        raise ValidationError()
    return current.update_comment(comment["id"], body.strip())


def delete_comment(actor, comment_id, *, store=None):
    current = _get_store(store)
    comment = _own_comment(current, actor, comment_id)
    current.delete_comment(comment["id"])
    return {"message": "Deleted"}


def create_announcement(actor, course_id, payload, *, store=None):
    current = _get_store(store)
    _course(current, course_id)
    if actor["role"] != "ADMIN" and not current.is_instructor_of(
        actor["id"], course_id
    ):
        raise Forbidden()
    title, body = _validate_post_fields(payload)
    return current.create_announcement(course_id, actor["id"], title, body)


def list_announcements(actor, course_id, *, store=None):
    current = _get_store(store)
    _course(current, course_id)
    _course_visible(current, actor, course_id)
    return current.list_announcements(course_id)


# ------------------------------------------------------------------ #
#  Admin                                                               #
# ------------------------------------------------------------------ #

VALID_ROLES = ("ADMIN", "INSTRUCTOR", "STUDENT")


def _require_admin(actor):
    if actor["role"] != "ADMIN":
        raise Forbidden()


def admin_list_users(actor, q=None, *, store=None):
    current = _get_store(store)
    _require_admin(actor)
    return current.list_users(q)


def admin_update_user(actor, user_id, payload, *, store=None):
    current = _get_store(store)
    _require_admin(actor)
    if not isinstance(payload, dict):
        raise ValidationError()
    role = payload.get("role")
    locked = payload.get("locked")
    if role is None and locked is None:
        raise ValidationError()
    target = current.get_user_by_id(user_id)
    if target is None:
        raise NotFound()
    if user_id == actor["id"]:
        raise Forbidden()  # cannot lock or demote your own admin account
    if role is not None:
        if role not in VALID_ROLES:
            raise ValidationError()
        current.set_user_role(user_id, role)
    if locked is not None:
        if not isinstance(locked, bool):
            raise ValidationError()
        current.set_user_lock(user_id, locked)
    updated = current.get_user_by_id(user_id)
    return {
        "id": updated["id"],
        "email": updated["email"],
        "role": updated["role"],
        "fullName": updated.get("full_name", ""),
        "locked": bool(updated.get("locked")),
    }


def admin_delete_course(actor, course_id, *, store=None):
    current = _get_store(store)
    _require_admin(actor)
    _course(current, course_id)
    current.delete_course(course_id)
    return {"message": "Deleted"}


def admin_read_audit(actor, limit=200, *, audit_path=None):
    _require_admin(actor)
    if not isinstance(limit, int) or not 1 <= limit <= 1000:
        limit = 200
    path = audit_path
    if path is None:
        from flask import current_app, has_app_context

        if has_app_context():
            path = current_app.config.get("AUDIT_LOG_PATH", "audit.log")
        else:
            path = "audit.log"
    entries = []
    p = Path(path)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
    return list(reversed(entries[-limit:]))
