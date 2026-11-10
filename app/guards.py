from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import g, has_request_context

from app.errors import Forbidden


def require_role(*roles: Any) -> Callable:
    """
    Route decorator requiring the authenticated actor to have one of the given roles.
    Checks flask.g.actor["role"]; wrong role raises Forbidden (403).
    Audit logging of 403 happens centrally in the Forbidden error handler.
    """
    allowed_roles: set[str] = set()
    for r in roles:
        if isinstance(r, (list, tuple, set)):
            allowed_roles.update(str(x) for x in r)
        else:
            allowed_roles.add(str(r))

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            actor = getattr(g, "actor", None) if has_request_context() else None
            role = actor.get("role") if isinstance(actor, dict) else None

            if role not in allowed_roles:
                raise Forbidden()

            return fn(*args, **kwargs)

        return wrapper

    return decorator
