import time

import bcrypt
import jwt
from flask import Blueprint, current_app, g, request

from .errors import AccountLocked, InvalidCredentials, Unauthenticated

bp = Blueprint("auth", __name__)

LOCK_THRESHOLD = 5
LOCK_SECONDS = 15 * 60

_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt(rounds=10))


def _now():
    return int(time.time())


def _failures():
    return current_app.extensions.setdefault("login_failures", {})


def _is_locked(email):
    entry = _failures().get(email)
    return (
        entry is not None
        and entry["locked_until"] is not None
        and _now() < entry["locked_until"]
    )


def _record_failure(email):
    failures = _failures()
    entry = failures.get(email)
    if entry is None:
        entry = {"count": 0, "locked_until": None}
    elif entry["locked_until"] is not None and _now() >= entry["locked_until"]:
        entry = {"count": 0, "locked_until": None}
    entry["count"] += 1
    if entry["count"] >= LOCK_THRESHOLD:
        entry["locked_until"] = _now() + LOCK_SECONDS
    failures[email] = entry


def create_token(user_id):
    now = _now()
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + int(current_app.config["TOKEN_TTL_SECONDS"]),
    }
    return jwt.encode(payload, current_app.config["JWT_SECRET"], algorithm="HS256")


def verify_token(token):
    try:
        payload = jwt.decode(
            token, current_app.config["JWT_SECRET"], algorithms=["HS256"]
        )
    except jwt.PyJWTError:
        raise Unauthenticated() from None
    sub = payload.get("sub")
    if not sub:
        raise Unauthenticated()
    return sub


@bp.post("/auth/login")
def login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "email" not in data or "password" not in data:
        raise InvalidCredentials()

    email, password = data["email"], data["password"]
    if _is_locked(email):
        raise AccountLocked()

    store = current_app.extensions["store"]
    user = store.get_user_by_email(email)
    pw_hash = store.get_password_hash_by_email(email) or _DUMMY_HASH
    ok = isinstance(password, str) and bcrypt.checkpw(password.encode(), pw_hash)

    if user is None or not ok:
        _record_failure(email)
        raise InvalidCredentials()

    _failures().pop(email, None)
    return {
        "accessToken": create_token(user["id"]),
        "expiresIn": int(current_app.config["TOKEN_TTL_SECONDS"]),
    }, 200


@bp.get("/me")
def me():
    actor = getattr(g, "actor", None)
    if actor is None:
        raise Unauthenticated()
    return {"id": actor["id"], "email": actor["email"], "role": actor["role"]}, 200
