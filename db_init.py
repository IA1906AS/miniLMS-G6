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
    version    INT NOT NULL DEFAULT 1,
    PRIMARY KEY (course_id, student_id)
);

ALTER TABLE enrollments ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id          VARCHAR(50)  PRIMARY KEY,
    course_id   VARCHAR(50)  NOT NULL REFERENCES courses(id),
    quiz_id     VARCHAR(50)  NOT NULL,
    student_id  VARCHAR(50)  NOT NULL REFERENCES users(id),
    answers     TEXT         NOT NULL DEFAULT '',
    score       NUMERIC(4,1),
    state       VARCHAR(20)  NOT NULL DEFAULT 'IN_PROGRESS'
                CHECK (state IN ('IN_PROGRESS', 'SUBMITTED', 'GRADED')),
    deadline    TIMESTAMPTZ  NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (course_id, quiz_id, student_id)
);

CREATE TABLE IF NOT EXISTS password_resets (
    email      VARCHAR(255) PRIMARY KEY,
    otp_hash   TEXT        NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS bio TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_path TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE courses ADD COLUMN IF NOT EXISTS code VARCHAR(20);
CREATE UNIQUE INDEX IF NOT EXISTS idx_courses_code ON courses(code);

CREATE TABLE IF NOT EXISTS materials (
    id            VARCHAR(50)  PRIMARY KEY,
    course_id     VARCHAR(50)  NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    uploader_id   VARCHAR(50)  NOT NULL REFERENCES users(id),
    original_name VARCHAR(255) NOT NULL,
    stored_name   VARCHAR(255) NOT NULL UNIQUE,
    size_bytes    BIGINT       NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assignments (
    id          VARCHAR(50)  PRIMARY KEY,
    course_id   VARCHAR(50)  NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title       VARCHAR(255) NOT NULL,
    description TEXT         NOT NULL DEFAULT '',
    due_at      TIMESTAMPTZ  NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS submissions (
    id             VARCHAR(50)  PRIMARY KEY,
    assignment_id  VARCHAR(50)  NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    student_id     VARCHAR(50)  NOT NULL REFERENCES users(id),
    original_name  VARCHAR(255) NOT NULL,
    stored_name    VARCHAR(255) NOT NULL UNIQUE,
    submitted_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    score          NUMERIC(4,1),
    feedback       TEXT,
    graded_at      TIMESTAMPTZ,
    UNIQUE (assignment_id, student_id)
);

CREATE TABLE IF NOT EXISTS quizzes (
    id           VARCHAR(50)  PRIMARY KEY,
    course_id    VARCHAR(50)  NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title        VARCHAR(255) NOT NULL,
    time_minutes INT          NOT NULL DEFAULT 30,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS questions (
    id         VARCHAR(50)  PRIMARY KEY,
    quiz_id    VARCHAR(50)  NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    position   INT          NOT NULL DEFAULT 1,
    text       TEXT         NOT NULL,
    options    TEXT         NOT NULL,
    answer_key VARCHAR(10)  NOT NULL,
    points     INT          NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS announcements (
    id         VARCHAR(50)  PRIMARY KEY,
    course_id  VARCHAR(50)  NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title      VARCHAR(255) NOT NULL,
    body       TEXT         NOT NULL,
    created_by VARCHAR(50)  NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS topics (
    id         VARCHAR(50)  PRIMARY KEY,
    course_id  VARCHAR(50)  NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    author_id  VARCHAR(50)  NOT NULL REFERENCES users(id),
    title      VARCHAR(255) NOT NULL,
    body       TEXT         NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS comments (
    id         VARCHAR(50)  PRIMARY KEY,
    topic_id   VARCHAR(50)  NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    author_id  VARCHAR(50)  NOT NULL REFERENCES users(id),
    body       TEXT         NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
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
