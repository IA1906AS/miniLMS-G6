"""
Re-export audit functionality from root audit module.
"""
from audit import AUDIT_LOG_PATH, log_event

__all__ = ["log_event", "AUDIT_LOG_PATH"]
