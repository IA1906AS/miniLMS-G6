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


def test_admin_endpoints_reject_non_admin(client):
    chi = token(client, "chi.sv@lms.test")
    assert client.get("/admin/users", headers=auth(chi)).status_code == 403
    assert client.patch(
        "/admin/users/u5", headers=auth(chi), json={"role": "ADMIN"}
    ).status_code == 403
    assert client.get("/admin/audit", headers=auth(chi)).status_code == 403


def test_lock_user_blocks_tokens_and_login(client):
    admin = token(client, "admin@lms.test")
    dung = token(client, "dung.sv@lms.test")

    locked = client.patch("/admin/users/u5", headers=auth(admin), json={"locked": True})
    assert locked.status_code == 200
    assert locked.json["locked"] is True
    # Existing token is rejected per-request by the gate.
    assert client.get("/me", headers=auth(dung)).status_code == 403
    # Fresh login is refused too.
    assert client.post(
        "/auth/login", json={"email": "dung.sv@lms.test", "password": "Lms@2026"}
    ).status_code == 429

    unlocked = client.patch("/admin/users/u5", headers=auth(admin), json={"locked": False})
    assert unlocked.json["locked"] is False
    assert token(client, "dung.sv@lms.test")


def test_admin_cannot_lock_or_demote_self(client):
    admin = token(client, "admin@lms.test")
    assert client.patch(
        "/admin/users/u1", headers=auth(admin), json={"locked": True}
    ).status_code == 403
    assert client.patch(
        "/admin/users/u1", headers=auth(admin), json={"role": "STUDENT"}
    ).status_code == 403


def test_role_change_takes_effect_immediately(client):
    admin = token(client, "admin@lms.test")
    dung = token(client, "dung.sv@lms.test")
    promoted = client.patch(
        "/admin/users/u5", headers=auth(admin), json={"role": "INSTRUCTOR"}
    )
    assert promoted.status_code == 200
    assert promoted.json["role"] == "INSTRUCTOR"
    me = client.get("/me", headers=auth(dung))
    assert me.json["role"] == "INSTRUCTOR"


def test_delete_course_cascades(client):
    admin = token(client, "admin@lms.test")
    em = token(client, "em.sv@lms.test")
    assert client.delete("/admin/courses/c2", headers=auth(admin)).status_code == 200
    ids = [c["id"] for c in client.get("/api/courses", headers=auth(admin)).json]
    assert "c2" not in ids
    # Quiz and enrollment of the removed course are gone with it.
    assert client.get("/courses/c2/quizzes/q3", headers=auth(em)).status_code == 404
    assert client.get("/members?courseId=c2", headers=auth(admin)).status_code == 404


def test_user_search_and_audit_viewer(client):
    admin = token(client, "admin@lms.test")
    found = client.get("/admin/users", headers=auth(admin), query_string={"q": "chi"}).json
    assert [u["id"] for u in found] == ["u4"]
    assert all("password" not in u and "passwordHash" not in u for u in found)

    client.delete("/admin/courses/c2", headers=auth(admin))
    audit = client.get("/admin/audit", headers=auth(admin)).json
    assert audit[0]["action"] == "ADMIN_DELETE_COURSE"
