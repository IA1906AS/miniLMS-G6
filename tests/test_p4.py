import pytest

from app import create_app
from app.errors import Forbidden, NotFound, ValidationError
from app.services import get_grades, update_grade


@pytest.fixture
def client(tmp_path):
    app = create_app({
        "JWT_SECRET": "x" * 32,
        "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
    })
    return app.test_client()


def token(client, email, password="Lms@2026"):
    response = client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return response.json["accessToken"]


def auth(token_value):
    return {"Authorization": f"Bearer {token_value}"}


def test_a7_a8_student_read_scope(client):
    chi = token(client, "chi.sv@lms.test")
    assert client.get("/courses/c1/grades", headers=auth(chi)).json == [
        {"studentId": "u4", "score": 7.5}
    ]
    assert client.get("/courses/c2/grades", headers=auth(chi)).status_code == 403


def test_a9_a11_students_and_admin_cannot_update(client):
    chi = token(client, "chi.sv@lms.test")
    admin = token(client, "admin@lms.test")
    for actor_token in (chi, admin):
        response = client.put(
            "/courses/c1/grades/u4",
            headers=auth(actor_token),
            json={"score": 10},
        )
        assert response.status_code == 403


def test_a10_a14_instructor_update_and_visibility(client):
    an = token(client, "an.gv@lms.test")
    chi = token(client, "chi.sv@lms.test")
    assert client.put(
        "/courses/c1/grades/u4",
        headers=auth(an),
        json={"score": 9},
    ).status_code == 200
    assert client.get("/courses/c1/grades", headers=auth(chi)).json == [
        {"studentId": "u4", "score": 9}
    ]


def test_a12_validation(client):
    an = token(client, "an.gv@lms.test")
    for score in (11, -1, "10", True):
        assert client.put(
            "/courses/c1/grades/u4",
            headers=auth(an),
            json={"score": score},
        ).status_code == 400
    assert client.put(
        "/courses/c1/grades/u4",
        headers=auth(an),
        json={"score": 9, "courseId": "c2"},
    ).status_code == 400


def test_a13_missing_enrollment(client):
    an = token(client, "an.gv@lms.test")
    assert client.put(
        "/courses/c1/grades/u6",
        headers=auth(an),
        json={"score": 5},
    ).status_code == 404


def test_a15_service_fails_closed_without_guard(client):
    store = client.application.extensions["store"]
    student = {"id": "u4", "email": "chi.sv@lms.test", "role": "STUDENT"}
    with pytest.raises(Forbidden):
        update_grade(student, "c1", "u4", 10, store=store)


def test_service_contract_and_errors(client):
    store = client.application.extensions["store"]
    instructor = {"id": "u2", "email": "an.gv@lms.test", "role": "INSTRUCTOR"}
    assert get_grades(instructor, "c1", store=store)
    with pytest.raises(NotFound):
        get_grades(instructor, "missing", store=store)
    with pytest.raises(ValidationError):
        update_grade(instructor, "c1", "u4", {"score": True}, store=store)
