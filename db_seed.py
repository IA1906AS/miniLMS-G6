"""
Seed PostgreSQL database from seed.json.

Usage:
    python db_seed.py

Run db_init.py first to create the tables.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
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
            cur.execute("DELETE FROM comments")
            cur.execute("DELETE FROM topics")
            cur.execute("DELETE FROM announcements")
            cur.execute("DELETE FROM questions")
            cur.execute("DELETE FROM quizzes")
            cur.execute("DELETE FROM submissions")
            cur.execute("DELETE FROM assignments")
            cur.execute("DELETE FROM materials")
            cur.execute("DELETE FROM password_resets")
            cur.execute("DELETE FROM quiz_attempts")
            cur.execute("DELETE FROM enrollments")
            cur.execute("DELETE FROM courses")
            cur.execute("DELETE FROM users")

            # ── Users ────────────────────────────────────────────────
            for u in seed["users"]:
                pw_hash = bcrypt.hashpw(
                    u["password"].encode(), bcrypt.gensalt(rounds=10)
                )
                cur.execute(
                    "INSERT INTO users (id, email, password_hash, role, full_name) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (u["id"], u["email"], pw_hash.decode("utf-8"), u["role"],
                     u.get("fullName", "")),
                )
                print(f"  + user  {u['id']}  {u['email']}  ({u['role']})")

            # ── Courses ──────────────────────────────────────────────
            for c in seed["courses"]:
                cur.execute(
                    "INSERT INTO courses (id, title, instructor_id, code) "
                    "VALUES (%s, %s, %s, %s)",
                    (c["id"], c["title"], c["instructorId"], c.get("code")),
                )
                print(f"  + course  {c['id']}  {c['title']}")

            # ── Quizzes and questions ────────────────────────────────
            for qz in seed.get("quizzes", []):
                cur.execute(
                    "INSERT INTO quizzes (id, course_id, title, time_minutes) "
                    "VALUES (%s, %s, %s, %s)",
                    (qz["id"], qz["courseId"], qz["title"], qz.get("timeMinutes", 30)),
                )
                print(f"  + quiz  {qz['id']}  {qz['courseId']}  {qz['title']}")
            for qs in seed.get("questions", []):
                cur.execute(
                    "INSERT INTO questions "
                    "(id, quiz_id, position, text, options, answer_key, points) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (qs["id"], qs["quizId"], qs.get("position", 1), qs["text"],
                     json.dumps(qs["options"]), qs["answer"], qs.get("points", 1)),
                )

            # ── Forum and announcements ──────────────────────────────
            for t in seed.get("topics", []):
                cur.execute(
                    "INSERT INTO topics (id, course_id, author_id, title, body) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (t["id"], t["courseId"], t["authorId"], t["title"], t["body"]),
                )
                print(f"  + topic  {t['id']}  {t['courseId']}  {t['title']}")
            for k in seed.get("comments", []):
                cur.execute(
                    "INSERT INTO comments (id, topic_id, author_id, body) "
                    "VALUES (%s, %s, %s, %s)",
                    (k["id"], k["topicId"], k["authorId"], k["body"]),
                )
            for n in seed.get("announcements", []):
                cur.execute(
                    "INSERT INTO announcements "
                    "(id, course_id, created_by, title, body) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (n["id"], n["courseId"], n["createdBy"], n["title"], n["body"]),
                )

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

            # ── Quiz attempts ──────────────────────────────────────
            for a in seed.get("quizAttempts", []):
                deadline = datetime.now(timezone.utc) + timedelta(
                    minutes=a["deadlineOffsetMinutes"]
                )
                cur.execute(
                    "INSERT INTO quiz_attempts "
                    "(id, course_id, quiz_id, student_id, answers, state, deadline) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (a["id"], a["courseId"], a["quizId"], a["studentId"],
                     a["answers"], a["state"], deadline),
                )
                print(
                    f"  + attempt  {a['id']}  {a['courseId']}/{a['quizId']}/"
                    f"{a['studentId']}  state={a['state']}"
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
