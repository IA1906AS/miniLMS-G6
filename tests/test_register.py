import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app({
        "JWT_SECRET": "x" * 32,
        "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
    })
    return app.test_client()


def login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_register_creates_student(client):
    body = {
        "email": "new.sv@lms.test",
        "password": "New@2026pass",
        "passwordConfirmation": "New@2026pass",
    }
    response = client.post("/auth/register", json=body)
    assert response.status_code == 201
    assert login(client, "new.sv@lms.test", "New@2026pass").status_code == 200
    token = login(client, "new.sv@lms.test", "New@2026pass").json["accessToken"]
    me = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json["role"] == "STUDENT"


def test_register_duplicate_email(client):
    body = {
        "email": "chi.sv@lms.test",
        "password": "New@2026pass",
        "passwordConfirmation": "New@2026pass",
    }
    response = client.post("/auth/register", json=body)
    assert response.status_code == 409
    assert response.json["error"] == "EMAIL_ALREADY_EXISTS"


def test_register_validation(client):
    for bad in (
        {"email": "not-an-email", "password": "New@2026pass", "passwordConfirmation": "New@2026pass"},
        {"email": "x@lms.test", "password": "short", "passwordConfirmation": "short"},
        {"email": "x@lms.test", "password": "New@2026pass", "passwordConfirmation": "different"},
    ):
        assert client.post("/auth/register", json=bad).status_code == 400
