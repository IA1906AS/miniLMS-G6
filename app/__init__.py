import os

from flask import Flask

from . import services
from .errors import register_error_handlers
from .gate import register_gate
from .pages import bp as pages_bp
from .routes import register_routes
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
    store = Store()
    app.extensions["store"] = store
    services.configure_store(store)

    register_gate(app)
    register_routes(app)
    app.register_blueprint(pages_bp)
    register_error_handlers(app)
    return app
