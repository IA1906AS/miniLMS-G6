"""
PostgreSQL connection pool for miniLMS-G6.

Reads database configuration from environment variables:
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

The pool is initialised lazily on the first call to get_connection()
and cleaned up automatically when the process exits.
"""

import atexit
import os

import psycopg2
from psycopg2 import pool as _pool

# ---------------------------------------------------------------------------
# Try to load .env so standalone scripts & Flask both pick up DB_* vars.
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass

# ---------------------------------------------------------------------------
# Module-level connection pool (singleton)
# ---------------------------------------------------------------------------
_connection_pool: _pool.SimpleConnectionPool | None = None


def get_db_config() -> dict:
    """Return a dict of psycopg2 connection keyword arguments."""
    return {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", "5432")),
        "dbname": os.environ.get("DB_NAME", "minilms_g6"),
        "user": os.environ.get("DB_USER", "postgres"),
        "password": os.environ.get("DB_PASSWORD", ""),
    }


def init_pool(minconn: int = 1, maxconn: int = 10) -> None:
    """Create the connection pool (idempotent)."""
    global _connection_pool
    if _connection_pool is not None:
        return
    config = get_db_config()
    _connection_pool = _pool.SimpleConnectionPool(minconn, maxconn, **config)
    atexit.register(close_pool)


def get_connection():
    """Borrow a connection from the pool (lazy-init on first call)."""
    if _connection_pool is None:
        init_pool()
    return _connection_pool.getconn()


def put_connection(conn) -> None:
    """Return a connection to the pool."""
    if _connection_pool is not None:
        _connection_pool.putconn(conn)


def close_pool() -> None:
    """Close every connection in the pool."""
    global _connection_pool
    if _connection_pool is not None:
        _connection_pool.closeall()
        _connection_pool = None
