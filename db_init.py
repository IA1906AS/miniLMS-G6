"""
Create PostgreSQL tables for miniLMS-G6.

Usage:
    python db_init.py

Requires DB_* environment variables (or a .env file with python-dotenv).
"""

import os
import sys

import psycopg2

# ---------------------------------------------------------------------------
# Load .env if python-dotenv is available
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# SQL – DDL
# ---------------------------------------------------------------------------
CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id          VARCHAR(50)  PRIMARY KEY,
    email       VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT       NOT NULL,
    role        VARCHAR(20)  NOT NULL
                CHECK (role IN ('ADMIN', 'INSTRUCTOR', 'STUDENT'))
);

CREATE TABLE IF NOT EXISTS courses (
    id            VARCHAR(50)  PRIMARY KEY,
    title         VARCHAR(255) NOT NULL,
    instructor_id VARCHAR(50)  NOT NULL REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS enrollments (
    course_id  VARCHAR(50) NOT NULL REFERENCES courses(id),
    student_id VARCHAR(50) NOT NULL REFERENCES users(id),
    score      NUMERIC(4,1),
    PRIMARY KEY (course_id, student_id)
);

CREATE TABLE IF NOT EXISTS password_resets (
    email      VARCHAR(255) PRIMARY KEY,
    otp_hash   TEXT        NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
"""


def _connect():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "minilms_g6"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
    )


def init_db():
    """Create all tables (idempotent thanks to IF NOT EXISTS)."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLES_SQL)
        conn.commit()
        print("[db_init] ✓ Tables created successfully.")
    except Exception as exc:
        conn.rollback()
        print(f"[db_init] ✗ Error: {exc}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
