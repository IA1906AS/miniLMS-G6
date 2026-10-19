import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from flask import g

from app import create_app
from app.gate import is_allowlisted, register_gate
from app.guards import require_role
from audit import log_event

SECRET = "s" * 32


@pytest.fixture
def app_with_gate(tmp_path):
    log_file = tmp_path / "test_audit.log"
    app = create_app(
        {
            "JWT_SECRET": SECRET,
            "AUDIT_LOG_PATH": str(log_file),
        }
    )
    register_gate(app)

    # Register sample routes to test gate and guards
    @app.get("/public-or-unregistered")
    def sample_route():
        return {"actor": g.actor}, 200

    @app.get("/admin-only")
    @require_role("ADMIN")
    def admin_only():
        return {"message": "hello admin"}, 200

    @app.get("/staff-only")
    @require_role("ADMIN", "INSTRUCTOR")
    def staff_only():
        return {"message": "hello staff"}, 200

    @app.put("/grades/<cid>/<sid>")
    @require_role("INSTRUCTOR")
    def update_grade(cid, sid):
        # Simulated grade edit done by P4
        old_score = 7.5
        new_score = 9.0
        log_event(
            actor_id=g.actor["id"],
            action="UPDATE_SCORE",
            resource=f"/grades/{cid}/{sid}",
            result="SUCCESS",
            extra={"oldScore": old_score, "newScore": new_score},
        )
        return {"status": "updated"}, 200

    return app


@pytest.fixture
def client(app_with_gate):
    return app_with_gate.test_client()


def make_token(sub: str, secret: str = SECRET, expires_in_seconds: int = 900) -> str:
    payload = {
        "sub": sub,
        "exp": datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# ==============================================================================
# Requirement 1: app/gate.py tests
# ==============================================================================


def test_gate_allowlist_matches_post_auth_login_only():
    assert is_allowlisted("POST", "/auth/login")
    assert is_allowlisted("POST", "/auth/login/")
    assert not is_allowlisted("GET", "/auth/login")
    assert not is_allowlisted("PUT", "/auth/login")
    assert not is_allowlisted("DELETE", "/auth/login")
    assert not is_allowlisted("POST", "/auth/login/extra")
    assert not is_allowlisted("POST", "/courses")


def test_gate_allowlist_post_auth_login_bypasses_auth(client):
    # Real login view rejects the empty body with INVALID_CREDENTIALS (401),
    # which proves the gate allowlisted the request: a blocked request would
    # get UNAUTHENTICATED instead.
    res = client.post("/auth/login")
    assert res.status_code == 401
    assert res.get_json() == {"error": "INVALID_CREDENTIALS"}


def test_gate_blocks_get_auth_login_without_token(client):
    res = client.get("/auth/login")
    assert res.status_code == 401
    assert res.get_json() == {"error": "UNAUTHENTICATED"}


def test_gate_default_deny_blocks_unknown_routes_without_token_a16(client):
    # Route does not even exist, yet gate intercepts and returns 401, NOT 404
    res = client.get("/nonexistent/endpoint")
    assert res.status_code == 401
    assert res.get_json() == {"error": "UNAUTHENTICATED"}


def test_gate_allows_authenticated_request_and_sets_actor(client):
    token = make_token("u1")  # admin user in seed.json
    res = client.get(
        "/public-or-unregistered",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    actor = res.get_json()["actor"]
    assert actor == {
        "id": "u1",
        "email": "admin@lms.test",
        "role": "ADMIN",
    }
    # No sensitive fields leaked
    assert "password" not in actor
    assert "password_hash" not in actor


def test_gate_rejects_missing_authorization_header(client):
    res = client.get("/public-or-unregistered")
    assert res.status_code == 401
    assert res.get_json() == {"error": "UNAUTHENTICATED"}


def test_gate_rejects_non_bearer_scheme(client):
    token = make_token("u1")
    res = client.get(
        "/public-or-unregistered",
        headers={"Authorization": f"Basic {token}"},
    )
    assert res.status_code == 401
    assert res.get_json() == {"error": "UNAUTHENTICATED"}


def test_gate_rejects_empty_bearer_token(client):
    res = client.get(
        "/public-or-unregistered",
        headers={"Authorization": "Bearer "},
    )
    assert res.status_code == 401
    assert res.get_json() == {"error": "UNAUTHENTICATED"}


def test_gate_rejects_malformed_token(client):
    res = client.get(
        "/public-or-unregistered",
        headers={"Authorization": "Bearer this-is-not-a-valid-jwt"},
    )
    assert res.status_code == 401
    assert res.get_json() == {"error": "UNAUTHENTICATED"}


def test_gate_rejects_wrong_secret(client):
    token = make_token("u1", secret="w" * 32)
    res = client.get(
        "/public-or-unregistered",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401
    assert res.get_json() == {"error": "UNAUTHENTICATED"}


def test_gate_rejects_expired_token(client):
    token = make_token("u1", expires_in_seconds=-10)
    res = client.get(
        "/public-or-unregistered",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401
    assert res.get_json() == {"error": "UNAUTHENTICATED"}


def test_gate_rejects_nonexistent_user_sub(client):
    token = make_token("u9999_nonexistent")
    res = client.get(
        "/public-or-unregistered",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401
    assert res.get_json() == {"error": "UNAUTHENTICATED"}


def test_gate_returns_404_for_authenticated_unmatched_route(client):
    token = make_token("u1")
    res = client.get(
        "/really/does/not/exist",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 404
    assert res.get_json() == {"error": "NOT_FOUND"}


# ==============================================================================
# Requirement 2: app/guards.py tests
# ==============================================================================


def test_require_role_permits_matching_role(client):
    token = make_token("u1")  # role: ADMIN
    res = client.get(
        "/admin-only",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.get_json() == {"message": "hello admin"}


def test_require_role_denies_wrong_role_and_logs_403(app_with_gate, client):
    token = make_token("u4")  # role: STUDENT
    res = client.get(
        "/admin-only",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403
    assert res.get_json() == {"error": "FORBIDDEN"}

    # Verify audit log was recorded on 403
    log_path = Path(app_with_gate.config["AUDIT_LOG_PATH"])
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    last_entry = json.loads(lines[-1])
    assert last_entry["actorId"] == "u4"
    assert last_entry["action"] == "GET"
    assert last_entry["resource"] == "/admin-only"
    assert last_entry["result"] == "FORBIDDEN"
    assert "ts" in last_entry


def test_require_role_supports_multiple_roles(client):
    admin_token = make_token("u1")  # ADMIN
    instructor_token = make_token("u2")  # INSTRUCTOR
    student_token = make_token("u4")  # STUDENT

    # Admin passes
    r1 = client.get("/staff-only", headers={"Authorization": f"Bearer {admin_token}"})
    assert r1.status_code == 200

    # Instructor passes
    r2 = client.get(
        "/staff-only", headers={"Authorization": f"Bearer {instructor_token}"}
    )
    assert r2.status_code == 200

    # Student denied
    r3 = client.get("/staff-only", headers={"Authorization": f"Bearer {student_token}"})
    assert r3.status_code == 403
    assert r3.get_json() == {"error": "FORBIDDEN"}


# ==============================================================================
# Requirement 3: audit.py tests
# ==============================================================================


def test_audit_log_format_and_score_update(tmp_path):
    log_file = tmp_path / "audit_test.log"
    os.environ["AUDIT_LOG_PATH"] = str(log_file)

    try:
        entry = log_event(
            actor_id="u2",
            action="UPDATE_SCORE",
            resource="/grades/c1/u4",
            result="SUCCESS",
            extra={"oldScore": 7.5, "newScore": 8.0},
        )
        assert entry["actorId"] == "u2"
        assert entry["action"] == "UPDATE_SCORE"
        assert entry["resource"] == "/grades/c1/u4"
        assert entry["result"] == "SUCCESS"
        assert entry["oldScore"] == 7.5
        assert entry["newScore"] == 8.0

        # Validate ISO 8601 timestamp
        datetime.fromisoformat(entry["ts"])

        # Verify disk contents
        content = log_file.read_text(encoding="utf-8").strip()
        disk_entry = json.loads(content)
        assert disk_entry["actorId"] == "u2"
        assert disk_entry["oldScore"] == 7.5
        assert disk_entry["newScore"] == 8.0
    finally:
        os.environ.pop("AUDIT_LOG_PATH", None)


def test_audit_log_a19_never_logs_passwords_or_tokens(tmp_path):
    log_file = tmp_path / "audit_security.log"
    os.environ["AUDIT_LOG_PATH"] = str(log_file)

    try:
        log_event(
            actor_id="u1",
            action="LOGIN_ATTEMPT",
            resource="/auth/login?password=supersecret&token=abc123jwt",
            result="FAILURE",
            extra={
                "password": "plaintext_password_123",
                "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy",
                "secret_key": "topsecret",
                "user_password_hash": "$2b$10$hashedstuff",
                "Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.dummy",
                "safe_note": "ok to log",
            },
        )

        content = log_file.read_text(encoding="utf-8")
        assert "plaintext_password_123" not in content
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in content
        assert "topsecret" not in content
        assert "$2b$10$hashedstuff" not in content
        assert "supersecret" not in content
        assert "abc123jwt" not in content

        disk_entry = json.loads(content.strip())
        assert "password" not in disk_entry
        assert "token" not in disk_entry
        assert "secret_key" not in disk_entry
        assert "user_password_hash" not in disk_entry
        assert "Authorization" not in disk_entry
        assert disk_entry["safe_note"] == "ok to log"
    finally:
        os.environ.pop("AUDIT_LOG_PATH", None)


def test_grade_update_triggers_audit_log(app_with_gate, client):
    token = make_token("u2")  # role: INSTRUCTOR
    res = client.put(
        "/grades/c1/u4",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200

    log_path = Path(app_with_gate.config["AUDIT_LOG_PATH"])
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    last_entry = json.loads(lines[-1])
    assert last_entry["actorId"] == "u2"
    assert last_entry["action"] == "UPDATE_SCORE"
    assert last_entry["resource"] == "/grades/c1/u4"
    assert last_entry["result"] == "SUCCESS"
    assert last_entry["oldScore"] == 7.5
    assert last_entry["newScore"] == 9.0
