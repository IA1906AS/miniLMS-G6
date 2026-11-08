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


def test_wrong_current_password_rejected(client):
    chi = token(client, "chi.sv@lms.test")
    response = client.post(
        "/auth/change-password",
        headers=auth(chi),
        json={"currentPassword": "Wrong@2026", "newPassword": "Fresh@2026"},
    )
    assert response.status_code == 400
    assert response.json["error"] == "INVALID_CURRENT_PASSWORD"


def test_change_password_revokes_token_and_allows_new_login(client):
    chi = token(client, "chi.sv@lms.test")
    response = client.post(
        "/auth/change-password",
        headers=auth(chi),
        json={"currentPassword": "Lms@2026", "newPassword": "Fresh@2026"},
    )
    assert response.status_code == 200
    assert client.get("/me", headers=auth(chi)).status_code == 401
    assert token(client, "chi.sv@lms.test", "Fresh@2026")


def test_logout_revokes_token(client):
    chi = token(client, "chi.sv@lms.test")
    assert client.post("/auth/logout", headers=auth(chi)).status_code == 200
    assert client.get("/me", headers=auth(chi)).status_code == 401
