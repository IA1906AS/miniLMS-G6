from app.errors import Forbidden, NotFound
from app.schemas import validate_grade_body, validate_score

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


def get_grades(actor, course_id, *, store=None):
    """Return only grades visible to actor; no Flask dependency."""
    current = _get_store(store)
    course = _course(current, course_id)
    rows = current.get_grades(course_id)

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
    return [{"studentId": row["studentId"], "score": row["score"]} for row in visible]


def update_grade(actor, course_id, student_id, score, *, store=None):
    """Update a grade with object authorization and strict validation."""
    current = _get_store(store)
    _course(current, course_id)

    if actor["role"] != "INSTRUCTOR" or not current.is_instructor_of(actor["id"], course_id):
        raise Forbidden()

    validated_score = validate_grade_body(score) if isinstance(score, dict) else validate_score(score)
    enrollment = current.get_enrollment(course_id, student_id)
    if enrollment is None:
        raise NotFound()

    old_score = enrollment["score"]
    current.set_score(course_id, student_id, validated_score)
    return old_score, validated_score
