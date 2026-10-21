"""Browser pages and the authenticated learning overview."""

from flask import Blueprint, current_app, g, render_template

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
    courses = []
    for course in store.courses.values():
        enrollment = store.get_enrollment(course["id"], actor["id"])
        if actor["role"] == "STUDENT" and enrollment is None:
            continue
        if actor["role"] == "INSTRUCTOR" and course["instructorId"] != actor["id"]:
            continue
        courses.append({
            "id": course["id"],
            "title": course["title"],
            "instructor": store.get_user_by_id(course["instructorId"])["email"],
            "score": enrollment["score"] if enrollment else None,
        })
    return {"courses": courses}
