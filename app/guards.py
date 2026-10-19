from functools import wraps
from typing import Any, Callable, Set

from flask import g, has_request_context, request

from app.errors import Forbidden

try:
    from audit import log_event
except ImportError:
    from app.audit import log_event


def require_role(*roles: Any) -> Callable:
    """
    Route decorator requiring the authenticated actor to have one of the given roles.
    Checks flask.g.actor["role"]. If not in allowed roles:
      - Logs audit event via log_event(actor_id, action, resource, "FORBIDDEN")
      - Raises Forbidden (403)
    """
    allowed_roles: Set[str] = set()
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
                actor_id = actor.get("id") if isinstance(actor, dict) else None
                action = request.method if has_request_context() else "ACCESS"
                resource = request.path if has_request_context() else getattr(fn, "__name__", "unknown")
                log_event(actor_id, action, resource, "FORBIDDEN")
                raise Forbidden()

            return fn(*args, **kwargs)

        return wrapper

    return decorator
