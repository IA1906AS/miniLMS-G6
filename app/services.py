from datetime import datetime, timedelta, timezone

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
