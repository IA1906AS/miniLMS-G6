import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app({
        "JWT_SECRET": "x" * 32,
        "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
    })
    return app.test_client()


def token(client, email, password="Lms@2026"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json["accessToken"]


def auth(token_value):
    return {"Authorization": f"Bearer {token_value}"}


def test_course_listing_is_role_scoped(client):
    chi = token(client, "chi.sv@lms.test")
    an = token(client, "an.gv@lms.test")
    admin = token(client, "admin@lms.test")
    assert [c["id"] for c in client.get("/api/courses", headers=auth(chi)).json] == ["c1"]
    assert [c["id"] for c in client.get("/api/courses", headers=auth(an)).json] == ["c1"]
    assert {c["id"] for c in client.get("/api/courses", headers=auth(admin)).json} == {"c1", "c2"}


def test_course_search(client):
    admin = token(client, "admin@lms.test")
    rows = client.get("/api/courses", headers=auth(admin), query_string={"q": "dữ liệu"}).json
    assert [c["id"] for c in rows] == ["c2"]
    assert rows[0]["code"] == "DB201"


def test_create_course_requires_unique_code(client):
    an = token(client, "an.gv@lms.test")
    ok = client.post(
        "/courses", headers=auth(an), json={"title": "An ninh mạng", "code": "SEC401"}
    )
    assert ok.status_code == 201
    dup = client.post(
        "/courses", headers=auth(an), json={"title": "Trùng mã", "code": "SEC401"}
    )
    assert dup.status_code == 409
    assert client.post(
        "/courses", headers=auth(token(client, "chi.sv@lms.test")),
        json={"title": "Sneaky", "code": "HAX999"},
    ).status_code == 403


def test_enroll_by_code(client):
    em = token(client, "em.sv@lms.test")
    ok = client.post("/courses/enroll", headers=auth(em), json={"code": "LMS101"})
    assert ok.status_code == 201
    assert ok.json["courseId"] == "c1"
    again = client.post("/courses/enroll", headers=auth(em), json={"code": "LMS101"})
    assert again.status_code == 409
    missing = client.post("/courses/enroll", headers=auth(em), json={"code": "NOPE1"})
    assert missing.status_code == 404


def test_instructor_adds_student(client):
    an = token(client, "an.gv@lms.test")
    ok = client.post("/courses/c1/students", headers=auth(an), json={"studentId": "u6"})
    assert ok.status_code == 201
    chi = token(client, "chi.sv@lms.test")
    rows = client.get("/members?courseId=c1", headers=auth(chi)).json
    assert "u6" in {r["id"] for r in rows}
