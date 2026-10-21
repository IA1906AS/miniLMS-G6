"""
db.py – PostgreSQL connection pool (psycopg2).

Cách dùng:
    from app.db import get_conn, init_pool, close_pool

Được khởi tạo qua init_app() trong create_app().
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor

# Module-level pool singleton — được tạo một lần khi app khởi động.
_pool: pg_pool.SimpleConnectionPool | None = None


def _dsn_from_env(cfg: dict) -> str:
    """
    Xây dựng DSN (Data Source Name) từ biến môi trường.

    Ưu tiên DATABASE_URL nếu có; nếu không, ghép từ các biến riêng lẻ:
      DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD.
    """
    url = cfg.get("DATABASE_URL")
    if url:
        return url

    host = cfg.get("DB_HOST", "localhost")
    port = cfg.get("DB_PORT", "5432")
    name = cfg.get("DB_NAME", "minilms")
    user = cfg.get("DB_USER", "postgres")
    password = cfg.get("DB_PASSWORD", "")

    return f"host={host} port={port} dbname={name} user={user} password={password}"


def init_pool(cfg: dict | None = None, minconn: int = 1, maxconn: int = 10) -> None:
    """
    Khởi tạo connection pool.
    Được gọi bởi create_app() trong __init__.py.

    Args:
        cfg: dict cấu hình (mặc định dùng os.environ).
        minconn: số kết nối tối thiểu giữ trong pool.
        maxconn: số kết nối tối đa cho phép.
    """
    global _pool
    if _pool is not None:
        return  # đã được khởi tạo

    env = cfg if cfg is not None else dict(os.environ)
    dsn = _dsn_from_env(env)

    _pool = pg_pool.SimpleConnectionPool(
        minconn=minconn,
        maxconn=maxconn,
        dsn=dsn,
    )


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

    Ví dụ:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM users WHERE email = %s", (email,))
                row = cur.fetchone()
    """
    if _pool is None:
        raise RuntimeError(
            "Database pool chưa được khởi tạo. "
            "Hãy gọi init_pool() trước (thông thường qua create_app())."
        )
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def get_cursor(conn: psycopg2.extensions.connection):
    """Trả về RealDictCursor để kết quả truy vấn là dict thay vì tuple."""
    return conn.cursor(cursor_factory=RealDictCursor)
