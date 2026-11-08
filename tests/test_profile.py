import io

import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app({
        "JWT_SECRET": "x" * 32,
        "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
        "UPLOAD_DIR": str(tmp_path / "uploads"),
    })
    return app.test_client()


def token(client, email, password="Lms@2026"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json["accessToken"]


def auth(token_value):
    return {"Authorization": f"Bearer {token_value}"}


def png(name="photo.png"):
    return (io.BytesIO(b"\x89PNG fake"), name)


def test_update_profile(client):
    chi = token(client, "chi.sv@lms.test")
    response = client.put(
        "/me",
        headers=auth(chi),
        json={"fullName": "Nguyễn Thị Chi", "bio": "Sinh viên năm 3", "phone": "0900"},
    )
    assert response.status_code == 200
    me = client.get("/me", headers=auth(chi)).json
    assert me["fullName"] == "Nguyễn Thị Chi"
    assert me["bio"] == "Sinh viên năm 3"
    assert me["phone"] == "0900"


def test_avatar_upload_and_public_fetch(client):
    chi = token(client, "chi.sv@lms.test")
    response = client.post(
        "/me/avatar", headers=auth(chi), data={"avatar": png()}, content_type="multipart/form-data"
    )
    assert response.status_code == 200
    url = response.json["avatarUrl"]
    assert url.startswith("/files/avatars/")
    # Avatars are served without auth for <img> tags.
    assert client.get(url).status_code == 200
    assert client.get("/me", headers=auth(chi)).json["avatarUrl"] == url


def test_avatar_rejects_bad_type(client):
    chi = token(client, "chi.sv@lms.test")
    response = client.post(
        "/me/avatar",
        headers=auth(chi),
        data={"avatar": (io.BytesIO(b"MZ"), "evil.exe")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_members_scoped_by_course(client):
    chi = token(client, "chi.sv@lms.test")
    admin = token(client, "admin@lms.test")
    rows = client.get("/members?courseId=c1", headers=auth(chi)).json
    assert {r["id"] for r in rows} == {"u2", "u4", "u5"}
    everyone = client.get("/members", headers=auth(admin)).json
    assert len(everyone) >= 6
    # Student cannot dump the whole user list.
    assert client.get("/members", headers=auth(chi)).status_code == 403
