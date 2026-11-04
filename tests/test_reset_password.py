import re
import time

import pytest

from app import create_app
from app import routes as routes_mod

SECRET = "s" * 32


@pytest.fixture
def client(tmp_path):
    app = create_app(
        {"JWT_SECRET": SECRET, "AUDIT_LOG_PATH": str(tmp_path / "audit.log")}
    )
    return app.test_client()


def login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def forgot(client, email):
    r = client.post("/auth/forgot-password", json={"email": email})
    assert r.status_code == 200
    return r.get_json()


def test_forgot_returns_8_digit_otp(client):
    body = forgot(client, "chi.sv@lms.test")
    assert re.fullmatch(r"\d{8}", body["otp"])


def test_reset_and_login_with_new_password(client):
    otp = forgot(client, "chi.sv@lms.test")["otp"]
    r = client.post(
        "/auth/reset-password",
        json={"email": "chi.sv@lms.test", "otp": otp, "newPassword": "NewPass@2026"},
    )
    assert r.status_code == 200
    assert login(client, "chi.sv@lms.test", "Lms@2026").status_code == 401
    assert login(client, "chi.sv@lms.test", "NewPass@2026").status_code == 200


def test_wrong_otp_is_one_shot(client):
    otp = forgot(client, "chi.sv@lms.test")["otp"]
    r = client.post(
        "/auth/reset-password",
        json={"email": "chi.sv@lms.test", "otp": "00000000", "newPassword": "NewPass@2026"},
    )
    assert r.status_code == 400
    assert r.get_json() == {"error": "INVALID_OTP"}
    # OTP đã bị xoá sau lần thử sai — dùng đúng OTP cũng không được nữa
    r2 = client.post(
        "/auth/reset-password",
        json={"email": "chi.sv@lms.test", "otp": otp, "newPassword": "NewPass@2026"},
    )
    assert r2.status_code == 400


def test_expired_otp_rejected_and_purged(client, monkeypatch):
    monkeypatch.setattr(routes_mod, "RESET_OTP_TTL_SECONDS", 1)
    otp = forgot(client, "chi.sv@lms.test")["otp"]
    time.sleep(1.5)
    r = client.post(
        "/auth/reset-password",
        json={"email": "chi.sv@lms.test", "otp": otp, "newPassword": "NewPass@2026"},
    )
    assert r.status_code == 400
    store = client.application.extensions["store"]
    assert store.get_reset_otp_hash("chi.sv@lms.test") is None


def test_forgot_unknown_email_same_response_shape(client):
    known = forgot(client, "chi.sv@lms.test")
    r = client.post("/auth/forgot-password", json={"email": "khongco@lms.test"})
    assert r.status_code == 200
    assert set(r.get_json()) == set(known)


def test_short_new_password_rejected(client):
    otp = forgot(client, "chi.sv@lms.test")["otp"]
    r = client.post(
        "/auth/reset-password",
        json={"email": "chi.sv@lms.test", "otp": otp, "newPassword": "short"},
    )
    assert r.status_code == 400
    assert r.get_json() == {"error": "VALIDATION_ERROR"}


def test_register_duplicate_email_rejected(client):
    r = client.post(
        "/auth/register",
        json={"email": "chi.sv@lms.test", "password": "Abcdef12", "passwordConfirmation": "Abcdef12"},
    )
    assert r.status_code == 409
    assert r.get_json() == {"error": "EMAIL_ALREADY_EXISTS"}
