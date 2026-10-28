import pytest

from app import create_app

SECRET = "s" * 32


@pytest.fixture
def store():
    return create_app({"JWT_SECRET": SECRET}).extensions["store"]


def test_a17_create_app_requires_jwt_secret():
    with pytest.raises(RuntimeError):
        create_app({"JWT_SECRET": ""})
    with pytest.raises(RuntimeError):
        create_app({"JWT_SECRET": "x" * 31})


def test_create_app_loads_fresh_store_each_call():
    app1 = create_app({"JWT_SECRET": SECRET})
    app2 = create_app({"JWT_SECRET": SECRET})
    assert app1.extensions["store"] is not app2.extensions["store"]


def test_config_overrides_env():
    app = create_app({"JWT_SECRET": SECRET, "TOKEN_TTL_SECONDS": "1"})
    assert app.config["TOKEN_TTL_SECONDS"] == 1
    assert app.config["AUDIT_LOG_PATH"] == "audit.log"


def test_store_hashes_passwords_at_load(store):
    h = store.get_password_hash_by_email("chi.sv@lms.test")
    assert h.startswith(b"$2")  # bcrypt


def test_store_grades_and_permissions(store):
    assert store.get_grades("c1") == [
        {"studentId": "u4", "score": 7.5},
        {"studentId": "u5", "score": 8.0},
    ]
    assert store.is_instructor_of("u2", "c1")
    assert not store.is_instructor_of("u3", "c1")
    assert not store.is_instructor_of("u2", "c2")
    assert store.get_user_by_id("u6") == {
        "id": "u6",
        "email": "em.sv@lms.test",
        "role": "STUDENT",
    }
    assert "password" not in store.get_user_by_id("u6")
    assert store.get_user_by_email("khongco@lms.test") is None
