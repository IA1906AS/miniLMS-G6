from typing import Any

import jwt
from flask import Flask, current_app, g, request

from app.errors import Unauthenticated

# Browser pages and their exact assets are public; data APIs remain protected.
PUBLIC_PAGES = {
    "/",
    "/home",
    "/account",
    "/login",
    "/register",
    "/static/app.css",
    "/static/app.js",
    "/static/css/base.css",
    "/static/css/auth.css",
    "/static/js/auth.js",
}

ALLOWLIST: set[tuple[str, str]] = {
    ("POST", "/auth/login"),
    ("POST", "/auth/register"),
}


def is_allowlisted(method: str, path: str) -> bool:
    """Check if the request method and path are allowlisted."""
    if (method, path) in ALLOWLIST:
        return True
    return bool(path.endswith("/") and (method, path.rstrip("/")) in ALLOWLIST)


def gate_before_request() -> Any | None:
    """Apply default-deny authentication to every non-public request."""
    if (request.method in {"GET", "HEAD"} and request.path in PUBLIC_PAGES) or is_allowlisted(
        request.method, request.path
    ):
        g.actor = None
        return None

    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise Unauthenticated()

    parts = auth_header.split(None, 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        raise Unauthenticated()

    token = parts[1].strip()
    secret = current_app.config.get("JWT_SECRET")
    if not token or not secret:
        raise Unauthenticated()

    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise Unauthenticated() from None

    if not isinstance(payload, dict) or not payload.get("sub"):
        raise Unauthenticated()

    store = current_app.extensions.get("store")
    user = store.get_user_by_id(payload["sub"]) if store else None
    if not user:
        raise Unauthenticated()

    g.actor = user
    return None


def register_gate(app: Flask) -> None:
    """Register the default-deny hook once."""
    if getattr(app, "_gate_registered", False):
        return
    app._gate_registered = True
    app.before_request(gate_before_request)


init_app = register_gate
init_gate = register_gate
gate_hook = register_gate
