"""
Seed PostgreSQL database from seed.json.

Usage:
    python db_seed.py

Run db_init.py first to create the tables.
"""

import json
import os
import sys
from pathlib import Path

import bcrypt
import psycopg2

# ---------------------------------------------------------------------------
# Load .env if python-dotenv is available
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

SEED_PATH = Path(__file__).resolve().parent / "seed.json"


def _connect():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "minilms_g6"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
    )


def seed_db():
    """Clear existing data and re-insert everything from seed.json."""
    with open(SEED_PATH, encoding="utf-8") as f:
        seed = json.load(f)

    conn = _connect()
    try:
        with conn.cursor() as cur:
            # Clear in reverse FK order
            cur.execute("DELETE FROM enrollments")
            cur.execute("DELETE FROM courses")
            cur.execute("DELETE FROM users")

            # ── Users ────────────────────────────────────────────────
            for u in seed["users"]:
                pw_hash = bcrypt.hashpw(
                    u["password"].encode(), bcrypt.gensalt(rounds=10)
                )
                cur.execute(
                    "INSERT INTO users (id, email, password_hash, role) "
                    "VALUES (%s, %s, %s, %s)",
                    (u["id"], u["email"], pw_hash.decode("utf-8"), u["role"]),
                )
                print(f"  + user  {u['id']}  {u['email']}  ({u['role']})")

            # ── Courses ──────────────────────────────────────────────
            for c in seed["courses"]:
                cur.execute(
                    "INSERT INTO courses (id, title, instructor_id) "
                    "VALUES (%s, %s, %s)",
                    (c["id"], c["title"], c["instructorId"]),
                )
                print(f"  + course  {c['id']}  {c['title']}")

            # ── Enrollments ──────────────────────────────────────────
            for e in seed["enrollments"]:
                cur.execute(
                    "INSERT INTO enrollments (course_id, student_id, score) "
                    "VALUES (%s, %s, %s)",
                    (e["courseId"], e["studentId"], e["score"]),
                )
                print(
                    f"  + enrollment  {e['courseId']} / {e['studentId']}  "
                    f"score={e['score']}"
                )

        conn.commit()
        print("\n[db_seed] ✓ Database seeded successfully.")
    except Exception as exc:
        conn.rollback()
        print(f"[db_seed] ✗ Error: {exc}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    seed_db()
