import base64
import json
import time
from pathlib import Path

import pytest

from app import create_app
from app.errors import Forbidden
from app.services import update_grade

SECRET = "s" * 32


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            "JWT_SECRET": SECRET,
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
        }
    )


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, email, password="Lms@2026"):
    return client.post("/auth/login", json={"email": email, "password": password})


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def token(client, email):
    r = login(client, email)
    assert r.status_code == 200
    return r.get_json()["accessToken"]


def test_a1_identical_login_errors(client):
    r1 = login(client, "khongco@lms.test")
    r2 = login(client, "chi.sv@lms.test", "sai-mat-khau")
    assert r1.status_code == r2.status_code == 401
    assert r1.get_json() == r2.get_json() == {"error": "INVALID_CREDENTIALS"}


def test_a2_me_without_token(client):
    assert client.get("/me").status_code == 401


def test_a3_tampered_sub(client):
    t = token(client, "chi.sv@lms.test")
    header, payload, sig = t.split(".")
    p = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    p["sub"] = "u1"
    forged_payload = (
        base64.urlsafe_b64encode(json.dumps(p).encode()).rstrip(b"=").decode()
    )
    forged = header + "." + forged_payload + "." + sig
    assert client.get("/me", headers=auth(forged)).status_code == 401


def test_a4_alg_none(client):
    b64 = lambda data: base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    header = b64(json.dumps({"alg": "none"}).encode())
    payload = b64(json.dumps({"sub": "u4", "exp": 4102444800}).encode())
    assert client.get("/me", headers=auth(header + "." + payload + ".")).status_code == 401


def test_a5_expired_token():
    app = create_app({"JWT_SECRET": SECRET, "TOKEN_TTL_SECONDS": "1"})
    client = app.test_client()
    t = token(client, "chi.sv@lms.test")
    time.sleep(2)
    assert client.get("/me", headers=auth(t)).status_code == 401


def test_a6_no_sensitive_fields_in_responses(client):
    chi = token(client, "chi.sv@lms.test")
    responses = [
        login(client, "khongco@lms.test"),
        login(client, "chi.sv@lms.test", "sai"),
        login(client, "chi.sv@lms.test"),
        client.get("/me"),
        client.get("/me", headers=auth(chi)),
        client.get("/courses/c1/grades", headers=auth(chi)),
    ]
    for r in responses:
        text = r.get_data(as_text=True)
        for needle in ("password", "password_hash", "passwordHash", "Lms@2026"):
            assert needle not in text


def test_a7_a8_student_scope(client):
    chi = token(client, "chi.sv@lms.test")
    r = client.get("/courses/c1/grades", headers=auth(chi))
    assert r.status_code == 200
    assert r.get_json() == [{"studentId": "u4", "score": 7.5}]
    assert client.get("/courses/c2/grades", headers=auth(chi)).status_code == 403


def test_a9_a10_a11_update_forbidden(client):
    chi = token(client, "chi.sv@lms.test")
    binh = token(client, "binh.gv@lms.test")
    admin = token(client, "admin@lms.test")
    assert client.put("/courses/c1/grades/u4", headers=auth(chi), json={"score": 10}).status_code == 403
    assert client.put("/courses/c1/grades/u4", headers=auth(binh), json={"score": 0}).status_code == 403
    assert client.put("/courses/c1/grades/u4", headers=auth(admin), json={"score": 10}).status_code == 403


def test_a12_validation(client):
    an = token(client, "an.gv@lms.test")
    for score in (11, -1, "10", True):
        r = client.put("/courses/c1/grades/u4", headers=auth(an), json={"score": score})
        assert r.status_code == 400
        assert r.get_json() == {"error": "VALIDATION_ERROR"}
    r = client.put(
        "/courses/c1/grades/u4",
        headers=auth(an),
        json={"score": 9, "courseId": "c2"},
    )
    assert r.status_code == 400


def test_a13_a14_update_and_visibility(client):
    an = token(client, "an.gv@lms.test")
    chi = token(client, "chi.sv@lms.test")
    assert client.put("/courses/c1/grades/u6", headers=auth(an), json={"score": 5}).status_code == 404
    r = client.put("/courses/c1/grades/u4", headers=auth(an), json={"score": 9})
    assert r.status_code == 200
    assert r.get_json() == {"courseId": "c1", "studentId": "u4", "score": 9}
    assert client.get("/courses/c1/grades", headers=auth(chi)).get_json() == [
        {"studentId": "u4", "score": 9}
    ]


def test_a15_service_fails_closed_without_guard():
    chi = {"id": "u4", "email": "chi.sv@lms.test", "role": "STUDENT"}
    with pytest.raises(Forbidden):
        update_grade(chi, "c1", "u4", 10)


def test_a16_undeclared_route_default_deny(client):
    app = client.application

    @app.get("/debug")
    def debug():
        return {"debug": True}

    assert client.get("/debug").status_code == 401


def test_a18_lockout(client):
    for _ in range(5):
        assert login(client, "dung.sv@lms.test", "sai").status_code == 401
    r = login(client, "dung.sv@lms.test")
    assert r.status_code == 429
    assert r.get_json() == {"error": "ACCOUNT_LOCKED"}


def test_a19_audit_log(app, client):
    binh = token(client, "binh.gv@lms.test")
    an = token(client, "an.gv@lms.test")
    assert client.put("/courses/c1/grades/u4", headers=auth(binh), json={"score": 0}).status_code == 403
    assert client.put("/courses/c1/grades/u4", headers=auth(an), json={"score": 9}).status_code == 200

    lines = Path(app.config["AUDIT_LOG_PATH"]).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    e403, e_update = (json.loads(line) for line in lines)
    assert e403["result"] == "FORBIDDEN"
    assert e403["actorId"] == "u3"
    assert e403["action"] == "PUT"
    assert e403["resource"] == "/courses/c1/grades/u4"
    assert e_update["action"] == "UPDATE_GRADE"
    assert e_update["result"] == "SUCCESS"
    assert e_update["oldScore"] == 7.5
    assert e_update["newScore"] == 9
    text = "\n".join(lines)
    assert "Lms@2026" not in text
    assert "password" not in text
    assert "eyJ" not in text
