import os
from pathlib import Path

from flask import Flask

from . import services
from .db import init_pool
from .errors import register_error_handlers
from .gate import register_gate
from .guards import ExportBulkhead
from .pages import bp as pages_bp
from .routes import register_routes
from .store_pg import PgStore


def create_app(config=None):
    cfg = dict(os.environ)
    if config:
        cfg.update(config)

    secret = cfg.get("JWT_SECRET")
    if not secret or len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be set and at least 32 characters long")

    app = Flask(__name__)
    # Chuẩn hoá UPLOAD_DIR thành đường dẫn tuyệt đối ngay khi nạp cấu hình:
    # save_upload() ghi tệp theo đường dẫn này, còn send_file()/
    # send_from_directory() của Flask phân giải đường dẫn tương đối theo
    # app.root_path (<repo>/app). Nếu giữ đường dẫn tương đối, tệp được ghi ở
    # <cwd>/uploads nhưng lại bị tìm ở <repo>/app/uploads -> tải tệp lỗi 500
    # và ảnh đại diện lỗi 404 với cấu hình mặc định.
    upload_dir = cfg.get("UPLOAD_DIR") or "uploads"
    app.config.update(
        JWT_SECRET=secret,
        TOKEN_TTL_SECONDS=int(cfg.get("TOKEN_TTL_SECONDS", 900)),
        AUDIT_LOG_PATH=cfg.get("AUDIT_LOG_PATH", "audit.log"),
        QUIZ_DEADLINE_MINUTES=int(cfg.get("QUIZ_DEADLINE_MINUTES", 120)),
        UPLOAD_DIR=str(Path(upload_dir).expanduser().resolve()),
        MAX_CONTENT_LENGTH=12 * 1024 * 1024,
    )

    # ── Khởi tạo PostgreSQL connection pool ──────────────────────────────
    init_pool(cfg)

    # ── Khởi tạo PgStore (PostgreSQL) thay cho Store (seed.json) ─────────
    store = PgStore()
    app.extensions["store"] = store
    app.extensions["grade_export_bulkhead"] = ExportBulkhead(limit=2)
    services.configure_store(store)

    register_gate(app)
    register_routes(app)
    app.register_blueprint(pages_bp)
    register_error_handlers(app)
    return app
