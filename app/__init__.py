import os

from flask import Flask

from . import services
<<<<<<< HEAD
from .auth import bp as auth_bp
from .db import close_pool, init_pool
=======
>>>>>>> 2a2df627005ef68dc8b0a21fd256c749b6708320
from .errors import register_error_handlers
from .gate import register_gate
from .pages import bp as pages_bp
from .routes import register_routes
<<<<<<< HEAD
from .store_pg import PgStore
from .pages import bp as pages_bp
=======
from .store import Store
>>>>>>> 2a2df627005ef68dc8b0a21fd256c749b6708320


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

    # ── Khởi tạo PostgreSQL connection pool ──────────────────────────────
    init_pool(cfg)

    # ── Khởi tạo PgStore (PostgreSQL) thay cho Store (seed.json) ─────────
    store = PgStore()
    app.extensions["store"] = store
    services.configure_store(store)

<<<<<<< HEAD
    # Đóng pool khi app context bị huỷ (graceful shutdown)
    @app.teardown_appcontext
    def _teardown(_exc):
        pass  # pool được dùng chung, không đóng theo từng request

    app.register_blueprint(auth_bp)
    app.register_blueprint(pages_bp)
=======
>>>>>>> 2a2df627005ef68dc8b0a21fd256c749b6708320
    register_gate(app)
    register_routes(app)
    app.register_blueprint(pages_bp)
    register_error_handlers(app)
    return app
