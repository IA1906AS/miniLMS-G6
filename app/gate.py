from typing import Any

import jwt
from flask import Flask, current_app, g, request

from app.errors import Unauthenticated

# Public pages and authentication actions are intentionally allowlisted.
ALLOWLIST: set[tuple[str, str]] = {
    ("GET", "/login"),
    ("GET", "/register"),
    ("GET", "/static/css/base.css"),
    ("GET", "/static/css/auth.css"),
    ("GET", "/static/js/auth.js"),
    ("POST", "/auth/login"),
    ("POST", "/auth/register"),
}


def is_allowlisted(method: str, path: str) -> bool:
    """Check if the request method and path are allowlisted."""
    if (method, path) in ALLOWLIST:
        return True
    return bool(path.endswith("/") and (method, path.rstrip("/")) in ALLOWLIST)


def gate_before_request() -> Any | None:
    """
    Global before_request hook enforcing default-deny authentication (A16, A2).

    1. Allowlist check: ONLY POST /auth/login bypasses authentication.
    2. All other requests require Authorization: Bearer <token>.
       - Missing, malformed, or expired token -> 401 UNAUTHENTICATED.
    3. Verify JWT using JWT_SECRET.
    4. Query store for user by sub. Non-existent -> 401 UNAUTHENTICATED.
    5. Assign actor (user dict) to flask.g.actor.
    """
    if is_allowlisted(request.method, request.path):
        g.actor = None
        return None

    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise Unauthenticated()

    parts = auth_header.split(None, 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        raise Unauthenticated()

    token = parts[1].strip()
    if not token:
        raise Unauthenticated()

    secret = current_app.config.get("JWT_SECRET")
    if not secret:
        raise Unauthenticated()

    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise Unauthenticated() from None

    if not isinstance(payload, dict):
        raise Unauthenticated()

    sub = payload.get("sub")
    if not sub:
        raise Unauthenticated()

    store = current_app.extensions.get("store")
    if store is None:
        raise Unauthenticated()

    user = store.get_user_by_id(sub)
    if not user:
        raise Unauthenticated()

    g.actor = user
    return None


def register_gate(app: Flask) -> None:
    """
    Hook for P1 to register before_request into create_app.
    Safe against multiple registrations.
    """
    if getattr(app, "_gate_registered", False):
        return
    app._gate_registered = True
    app.before_request(gate_before_request)


# Aliases for hook registration
init_app = register_gate
init_gate = register_gate
gate_hook = register_gate
