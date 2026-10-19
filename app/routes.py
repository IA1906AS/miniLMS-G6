from flask import current_app, g, jsonify, request

from audit import log_event
from app import services
from app.guards import require_role


def register_routes(app):
    """Register P4 routes; P1 app factory calls this once after Store setup."""

    @app.get("/courses/<course_id>/grades")
    @require_role("ADMIN", "INSTRUCTOR", "STUDENT")
    def get_course_grades(course_id):
        store = current_app.extensions["store"]
        rows = services.get_grades(g.actor, course_id, store=store)
        return jsonify(rows), 200

    @app.put("/courses/<course_id>/grades/<student_id>")
    @require_role("ADMIN", "INSTRUCTOR")
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
