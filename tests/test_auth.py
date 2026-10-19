import base64
import json
import time

import pytest
from flask import g

from app import create_app
from app.auth import create_token, verify_token
from app.auth import me as me_view
from app.errors import Unauthenticated

SECRET = "s" * 32


@pytest.fixture
def app():
    return create_app({"JWT_SECRET": SECRET})


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_a1_identical_error_for_unknown_email_and_wrong_password(client):
    r1 = login(client, "khongco@lms.test", "Lms@2026")
    r2 = login(client, "chi.sv@lms.test", "sai-mat-khau")
    assert r1.status_code == r2.status_code == 401
    assert r1.get_json() == r2.get_json() == {"error": "INVALID_CREDENTIALS"}


def test_login_success(client):
    r = login(client, "chi.sv@lms.test", "Lms@2026")
    assert r.status_code == 200
    body = r.get_json()
    assert isinstance(body["accessToken"], str)
    assert body["expiresIn"] == 900
    assert set(body) == {"accessToken", "expiresIn"}


def test_a3_tampered_sub_rejected(app):
    with app.app_context():
        token = create_token("u4")
        header, payload, sig = token.split(".")
        p = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        p["sub"] = "u1"
        forged_payload = (
            base64.urlsafe_b64encode(json.dumps(p).encode()).rstrip(b"=").decode()
        )
        forged = header + "." + forged_payload + "." + sig
        with pytest.raises(Unauthenticated):
            verify_token(forged)


def test_a4_alg_none_rejected(app):
    def b64(data):
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "none"}).encode())
    payload = b64(json.dumps({"sub": "u4", "exp": int(time.time()) + 999}).encode())
    with app.app_context():
        with pytest.raises(Unauthenticated):
            verify_token(header + "." + payload + ".")


def test_a5_expired_token_rejected():
    app = create_app({"JWT_SECRET": SECRET, "TOKEN_TTL_SECONDS": "1"})
    with app.app_context():
        token = create_token("u4")
    time.sleep(2)
    with app.app_context():
        with pytest.raises(Unauthenticated):
            verify_token(token)


def test_a18_lockout_after_5_failures(client):
    for _ in range(5):
        assert login(client, "dung.sv@lms.test", "sai").status_code == 401
    r = login(client, "dung.sv@lms.test", "Lms@2026")
    assert r.status_code == 429
    assert r.get_json() == {"error": "ACCOUNT_LOCKED"}


def test_lock_resets_on_success_before_threshold(client):
    assert login(client, "em.sv@lms.test", "sai").status_code == 401
    assert login(client, "em.sv@lms.test", "Lms@2026").status_code == 200
    assert login(client, "em.sv@lms.test", "sai").status_code == 401
    assert login(client, "em.sv@lms.test", "Lms@2026").status_code == 200


def test_me_returns_contract_fields_only(app):
    with app.test_request_context():
        g.actor = {
            "id": "u4",
            "email": "chi.sv@lms.test",
            "role": "STUDENT",
            "password_hash": b"leak-check",
        }
        assert me_view() == (
            {"id": "u4", "email": "chi.sv@lms.test", "role": "STUDENT"},
            200,
        )


def test_me_without_actor_is_401(app):
    with app.test_request_context():
        with pytest.raises(Unauthenticated):
            me_view()
