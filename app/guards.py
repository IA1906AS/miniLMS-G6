from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from threading import Lock
from typing import Any

from flask import g, has_request_context

from app.errors import Forbidden


class ExportBusy(Exception):
    """No grade-export capacity remains in this process."""


class ExportBulkhead:
    """Bound concurrent exports without making callers wait for a slot."""

    def __init__(self, limit=2):
        self.limit = limit
        self._active = 0
        self._lock = Lock()

    @contextmanager
    def slot(self):
        with self._lock:
            if self._active >= self.limit:
                raise ExportBusy()
            self._active += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1


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
