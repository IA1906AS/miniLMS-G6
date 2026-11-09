"""
db.py – PostgreSQL connection pool (psycopg2).

Cách dùng:
    from app.db import get_conn, init_pool, close_pool

Được khởi tạo qua init_app() trong create_app().

Kết nối và thao tác lấy connection từ pool được retry với exponential backoff
kèm full jitter (xem app/retry.py) để chịu được lỗi tạm thời khi database khởi
động chậm hoặc pool tạm thời cạn. Lỗi truy vấn/transaction KHÔNG retry tự động
để tránh lặp lại hiệu ứng phụ (ghi dữ liệu hai lần).
"""

from __future__ import annotations

import atexit
import logging
import os
from contextlib import contextmanager
from typing import Generator

import psycopg2
from dotenv import load_dotenv
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor

from .retry import RetryPolicy, retry_call

load_dotenv()

logger = logging.getLogger(__name__)

# Module-level pool singleton — được tạo một lần khi app khởi động.
_pool: pg_pool.ThreadedConnectionPool | None = None

# Chính sách retry hiện hành; được nạp từ biến môi trường trong init_pool().
_retry_policy = RetryPolicy()


def _env_int(env, key: str, default: int) -> int:
    """Đọc một biến môi trường dạng số nguyên, báo lỗi rõ ràng nếu sai định dạng."""
    raw = env.get(key, default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise RuntimeError(f"{key} must be an integer, got {raw!r}") from None


def _retry_policy_from(env) -> RetryPolicy:
    """Tạo RetryPolicy từ cấu hình môi trường (DB_RETRY_*)."""
    attempts = _env_int(env, "DB_RETRY_ATTEMPTS", 4)
    base_ms = _env_int(env, "DB_RETRY_BASE_DELAY_MS", 100)
    max_ms = _env_int(env, "DB_RETRY_MAX_DELAY_MS", 2000)

    if attempts < 1:
        raise RuntimeError("DB_RETRY_ATTEMPTS must be at least 1")
    if base_ms < 0:
        raise RuntimeError("DB_RETRY_BASE_DELAY_MS must be >= 0")
    if max_ms < base_ms:
        raise RuntimeError("DB_RETRY_MAX_DELAY_MS must be >= DB_RETRY_BASE_DELAY_MS")

    return RetryPolicy(
        attempts=attempts,
        base_delay=base_ms / 1000.0,
        max_delay=max_ms / 1000.0,
    )


def _retry_logger(action: str, policy: RetryPolicy):
    """Trả về callback ghi log mỗi lần retry (không log stack trace cho lỗi tạm thời)."""

    def _on_retry(exc: BaseException, attempt: int, delay: float) -> None:
        logger.warning(
            "DB %s failed (%d/%d): %s; retrying in %.3fs",
            action,
            attempt,
            policy.attempts,
            exc,
            delay,
        )

    return _on_retry


def _create_pool(env, minconn: int, maxconn: int) -> pg_pool.ThreadedConnectionPool:
    """Tạo pool mới; tách riêng để kiểm thử có thể thay thế."""
    return pg_pool.ThreadedConnectionPool(
        minconn=minconn,
        maxconn=maxconn,
        **_connection_args(env),
    )


def _connection_args(cfg: dict) -> dict:
    """
    Tạo tham số kết nối từ cấu hình môi trường.

    Ưu tiên DATABASE_URL nếu có; nếu không, ghép từ các biến riêng lẻ:
      DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD.
    """
    url = cfg.get("DATABASE_URL")
    if url:
        return {"dsn": url}
    return {
        "host": cfg.get("DB_HOST", "localhost"),
        "port": int(cfg.get("DB_PORT", "5432")),
        "dbname": cfg.get("DB_NAME", "minilms_g6"),
        "user": cfg.get("DB_USER", "postgres"),
        "password": cfg.get("DB_PASSWORD", ""),
    }


def init_pool(cfg: dict | None = None, minconn: int = 1, maxconn: int = 10) -> None:
    """
    Khởi tạo connection pool.
    Được gọi bởi create_app() trong __init__.py.

    Việc tạo pool (kết nối tới PostgreSQL) được retry với exponential backoff
    kèm full jitter khi gặp lỗi tạm thời, nhờ đó app vẫn khởi động được nếu
    database chậm sẵn sàng vài giây.

    Args:
        cfg: dict cấu hình (mặc định dùng os.environ).
        minconn: số kết nối tối thiểu giữ trong pool.
        maxconn: số kết nối tối đa cho phép.
    """
    global _pool, _retry_policy
    if _pool is not None:
        return  # đã được khởi tạo

    env = cfg if cfg is not None else os.environ
    _retry_policy = _retry_policy_from(env)
    _pool = retry_call(
        lambda: _create_pool(env, minconn, maxconn),
        policy=_retry_policy,
        retry_on=(psycopg2.OperationalError, psycopg2.InterfaceError, pg_pool.PoolError),
        on_retry=_retry_logger("connect", _retry_policy),
    )
    atexit.register(close_pool)


def close_pool() -> None:
    """Đóng toàn bộ kết nối trong pool. Gọi khi tắt app."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


@contextmanager
def get_conn() -> Generator[psycopg2.extensions.connection, None, None]:
    """
    Context manager lấy connection từ pool, tự trả lại sau khi dùng xong.

    Việc lấy connection được retry với backoff + jitter khi pool tạm thời cạn
    (PoolError) hoặc connection trong pool đã chết (OperationalError /
    InterfaceError). Exception phát sinh bên trong khối ``with`` không được
    retry — transaction được rollback và lỗi được ném lại cho caller.

    Ví dụ:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM users WHERE email = %s", (email,))
                row = cur.fetchone()
    """
    pool = _pool
    if pool is None:
        raise RuntimeError(
            "Database pool chưa được khởi tạo. "
            "Hãy gọi init_pool() trước (thông thường qua create_app())."
        )

    conn = retry_call(
        pool.getconn,
        policy=_retry_policy,
        retry_on=(pg_pool.PoolError, psycopg2.OperationalError, psycopg2.InterfaceError),
        on_retry=_retry_logger("checkout", _retry_policy),
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def get_cursor(conn: psycopg2.extensions.connection):
    """Trả về RealDictCursor để kết quả truy vấn là dict thay vì tuple."""
    return conn.cursor(cursor_factory=RealDictCursor)
