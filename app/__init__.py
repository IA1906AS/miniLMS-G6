import os

from flask import Flask

from .errors import register_error_handlers
from .store import Store


def create_app(config=None):
    cfg = dict(os.environ)
    if config:
        cfg.update(config)

    secret = cfg.get("JWT_SECRET")
    if not secret or len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be set and at least 32 characters long")

    app = Flask(__name__)
    app.config.update(
        JWT_SECRET=secret,
        TOKEN_TTL_SECONDS=int(cfg.get("TOKEN_TTL_SECONDS", 900)),
        AUDIT_LOG_PATH=cfg.get("AUDIT_LOG_PATH", "audit.log"),
    )
    app.extensions["store"] = Store()

    register_error_handlers(app)
    return app
