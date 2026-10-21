#!/usr/bin/env python
"""
migrate.py – Tạo bảng PostgreSQL và seed dữ liệu từ seed.json.

Chạy một lần trước khi khởi động app:
    python migrate.py

Biến môi trường cần có (hoặc đặt trong .env):
    DATABASE_URL   — ưu tiên nếu có
    hoặc: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

Script này:
  1. Tạo các bảng users, courses, enrollments (nếu chưa có).
  2. Seed dữ liệu từ seed.json vào DB (bỏ qua nếu đã tồn tại).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import bcrypt
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Nạp biến môi trường từ .env nếu có
load_dotenv()

SEED_PATH = Path(__file__).resolve().parent / "seed.json"

# ─── DDL ──────────────────────────────────────────────────────────────────────

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash BYTEA       NOT NULL,
    role          TEXT        NOT NULL CHECK (role IN ('ADMIN','INSTRUCTOR','STUDENT')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

CREATE_COURSES = """
CREATE TABLE IF NOT EXISTS courses (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    instructor_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

CREATE_ENROLLMENTS = """
CREATE TABLE IF NOT EXISTS enrollments (
    course_id  TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    student_id TEXT NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    score      NUMERIC(5,2),
    enrolled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (course_id, student_id)
);
"""

# Index để tăng tốc lookup theo email và instructor
CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_users_email        ON users(email);",
    "CREATE INDEX IF NOT EXISTS idx_courses_instructor ON courses(instructor_id);",
    "CREATE INDEX IF NOT EXISTS idx_enroll_student     ON enrollments(student_id);",
]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _dsn() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "minilms_g6")
    user = os.getenv("DB_USER", "postgres")
    pw   = os.getenv("DB_PASSWORD", "")
    return f"host={host} port={port} dbname={name} user={user} password={pw}"


def _create_tables(cur: psycopg2.extensions.cursor) -> None:
    print("  → Tạo bảng users …")
    cur.execute(CREATE_USERS)
    print("  → Tạo bảng courses …")
    cur.execute(CREATE_COURSES)
    print("  → Tạo bảng enrollments …")
    cur.execute(CREATE_ENROLLMENTS)
    for idx_sql in CREATE_INDEXES:
        cur.execute(idx_sql)
    print("  → Indexes đã sẵn sàng.")


def _seed_data(cur: psycopg2.extensions.cursor, seed: dict) -> None:
    # ── Users ──
    print("  → Seed users …")
    for u in seed["users"]:
        pw_hash = bcrypt.hashpw(u["password"].encode(), bcrypt.gensalt(rounds=10))
        cur.execute(
            """
            INSERT INTO users (id, email, password_hash, role)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (u["id"], u["email"], pw_hash, u["role"]),
        )

    # ── Courses ──
    print("  → Seed courses …")
    for c in seed["courses"]:
        cur.execute(
            """
            INSERT INTO courses (id, title, instructor_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (c["id"], c["title"], c["instructorId"]),
        )

    # ── Enrollments ──
    print("  → Seed enrollments …")
    for e in seed["enrollments"]:
        cur.execute(
            """
            INSERT INTO enrollments (course_id, student_id, score)
            VALUES (%s, %s, %s)
            ON CONFLICT (course_id, student_id) DO NOTHING
            """,
            (e["courseId"], e["studentId"], e.get("score")),
        )


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    dsn = _dsn()
    print(f"Kết nối PostgreSQL …  (host={os.getenv('DB_HOST','localhost')})")

    try:
        conn = psycopg2.connect(dsn)
    except psycopg2.OperationalError as exc:
        print(f"\n[LỖI] Không thể kết nối PostgreSQL:\n  {exc}")
        print("\nKiểm tra lại biến môi trường DB_HOST / DB_NAME / DB_USER / DB_PASSWORD hoặc DATABASE_URL.")
        sys.exit(1)

    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                print("\n[1/2] Tạo schema …")
                _create_tables(cur)

                print("\n[2/2] Seed dữ liệu từ seed.json …")
                if SEED_PATH.exists():
                    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
                    _seed_data(cur, seed)
                else:
                    print(f"  ⚠ Không tìm thấy {SEED_PATH} — bỏ qua seed.")

        print("\n✅ Migration hoàn tất thành công!")
    except Exception as exc:
        print(f"\n[LỖI] Migration thất bại:\n  {exc}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
