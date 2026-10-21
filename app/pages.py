"""Browser pages and the authenticated learning overview."""

from flask import Blueprint, current_app, g, render_template

from app.errors import Forbidden

bp = Blueprint("pages", __name__)


@bp.get("/")
@bp.get("/home")
@bp.get("/account")
def index():
    return render_template("index.html")


@bp.get("/dashboard")
def dashboard():
    store = current_app.extensions["store"]
    actor = g.actor
    if actor["role"] not in {"ADMIN", "INSTRUCTOR", "STUDENT"}:
        raise Forbidden()

    # Dùng get_all_courses() để lấy một lần duy nhất từ DB
    all_courses = store.get_all_courses()

    courses = []
    for course in all_courses:
        enrollment = store.get_enrollment(course["id"], actor["id"])
        if actor["role"] == "STUDENT" and enrollment is None:
            continue
        if actor["role"] == "INSTRUCTOR" and course["instructorId"] != actor["id"]:
            continue
        instructor = store.get_user_by_id(course["instructorId"])
        courses.append({
            "id": course["id"],
            "title": course["title"],
            "instructor": instructor["email"] if instructor else "",
            "score": enrollment["score"] if enrollment else None,
        })
    return {"courses": courses}
