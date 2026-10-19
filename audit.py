import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Default audit log path
DEFAULT_AUDIT_LOG_PATH = "audit.log"
AUDIT_LOG_PATH = os.environ.get("AUDIT_LOG_PATH", DEFAULT_AUDIT_LOG_PATH)

# Substrings identifying sensitive fields that must NEVER appear in audit log (A19)
SENSITIVE_KEY_SUBSTRINGS = (
    "password",
    "token",
    "secret",
    "hash",
    "credential",
    "auth",
    "bearer",
)


def _get_audit_log_path() -> str:
    """Determine audit log path from Flask application config or environment."""
    try:
        from flask import current_app, has_app_context

        if has_app_context() and current_app:
            return current_app.config.get("AUDIT_LOG_PATH", AUDIT_LOG_PATH)
    except ImportError, RuntimeError:
        pass
    return os.environ.get("AUDIT_LOG_PATH", AUDIT_LOG_PATH)


def _is_sensitive_key(key: str) -> bool:
    """Check if a key name suggests sensitive credentials/tokens."""
    k = key.lower()
    return any(sub in k for sub in SENSITIVE_KEY_SUBSTRINGS)


def _sanitize_string(val: str) -> str:
    """Redact sensitive credentials or tokens embedded inside string values."""
    if not isinstance(val, str):
        return val
    # Redact Bearer tokens
    val = re.sub(
        r"Bearer\s+[A-Za-z0-9\-._~+/]+=*",
        "Bearer [REDACTED]",
        val,
        flags=re.IGNORECASE,
    )
    # Redact URL query params or headers with sensitive data
    val = re.sub(
        r"(password|token|secret|credential)=[^&\s]+",
        r"\1=[REDACTED]",
        val,
        flags=re.IGNORECASE,
    )
    return val


def _sanitize_value(val: Any) -> Any:
    """Recursively sanitize values to prevent leaking passwords or tokens."""
    if isinstance(val, str):
        return _sanitize_string(val)
    if isinstance(val, dict):
        return {
            k: _sanitize_value(v) for k, v in val.items() if not _is_sensitive_key(k)
        }
    if isinstance(val, (list, tuple, set)):
        return [_sanitize_value(item) for item in val]
    return val


def log_event(
    actor_id: str | None,
    action: str,
    resource: str,
    result: str,
    extra: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Append 1 JSON line to AUDIT_LOG_PATH.
    Fields:
      - ts (ISO 8601)
      - actorId
      - action
      - resource
      - result
      - oldScore / newScore when updating score
    Guarantees no passwords or tokens are logged (A19).
    """
    ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    record: dict[str, Any] = {
        "ts": ts,
        "actorId": actor_id,
        "action": _sanitize_string(action),
        "resource": _sanitize_string(resource),
        "result": _sanitize_string(result),
    }

    # Merge extra and kwargs
    merged_extra: dict[str, Any] = {}
    if extra and isinstance(extra, dict):
        merged_extra.update(extra)
    if kwargs:
        merged_extra.update(kwargs)

    # Support oldScore / newScore (both camelCase and snake_case)
    if "oldScore" in merged_extra:
        record["oldScore"] = merged_extra["oldScore"]
    elif "old_score" in merged_extra:
        record["oldScore"] = merged_extra["old_score"]

    if "newScore" in merged_extra:
        record["newScore"] = merged_extra["newScore"]
    elif "new_score" in merged_extra:
        record["newScore"] = merged_extra["new_score"]

    # Include other safe extra attributes
    for k, v in merged_extra.items():
        if k in ("oldScore", "old_score", "newScore", "new_score"):
            continue
        if _is_sensitive_key(k):
            continue
        record[k] = _sanitize_value(v)

    target_path = _get_audit_log_path()
    p = Path(target_path)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)

    json_line = json.dumps(record, ensure_ascii=False)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json_line + "\n")

    return record
