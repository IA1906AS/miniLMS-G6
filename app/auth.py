import time
from uuid import uuid4

import bcrypt
import jwt
from flask import current_app, g

from .errors import AccountLocked, InvalidCredentials, Unauthenticated

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
        "jti": uuid4().hex,
        "iat": now,
        "exp": now + int(current_app.config["TOKEN_TTL_SECONDS"]),
    }
    return jwt.encode(payload, current_app.config["JWT_SECRET"], algorithm="HS256")


# ponytail: in-memory per-process revocation, same scope as the login throttle
def _revoked():
    return current_app.extensions.setdefault("revoked_tokens", {})


def revoke_token(payload):
    jti = payload.get("jti")
    if not jti:
        return
    registry = _revoked()
    registry[jti] = payload.get("exp", 0)
    now = _now()
    for expired in [k for k, v in registry.items() if v < now]:
        del registry[expired]


def is_revoked(payload):
    jti = payload.get("jti")
    return bool(jti) and jti in _revoked()


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


def me():
    actor = getattr(g, "actor", None)
    if actor is None:
        raise Unauthenticated()
    return {
        "id": actor["id"],
        "email": actor["email"],
        "role": actor["role"],
        "fullName": actor.get("full_name", ""),
        "bio": actor.get("bio", ""),
        "phone": actor.get("phone", ""),
        "avatarUrl": (
            f"/files/avatars/{actor['avatar_path']}"
            if actor.get("avatar_path")
            else None
        ),
    }, 200
