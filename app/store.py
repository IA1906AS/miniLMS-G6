"""
PostgreSQL-backed data store for miniLMS-G6.

Provides the **same public interface** as the original in-memory Store
so that auth.py, services.py, routes.py, pages.py, gate.py, etc.
continue to work without any changes.
"""

from app.database import get_connection, put_connection


class Store:
    """All queries go straight to PostgreSQL via psycopg2."""

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _public(row):
        """Convert a (id, email, role) tuple to the public user dict."""
        return {"id": row[0], "email": row[1], "role": row[2]}

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------

    def get_user_by_email(self, email):
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, email, role FROM users WHERE email = %s",
                    (email,),
                )
                row = cur.fetchone()
                return self._public(row) if row else None
        finally:
            put_connection(conn)

    def get_user_by_id(self, uid):
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, email, role FROM users WHERE id = %s",
                    (uid,),
                )
                row = cur.fetchone()
                return self._public(row) if row else None
        finally:
            put_connection(conn)

    def get_password_hash_by_email(self, email):
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT password_hash FROM users WHERE email = %s",
                    (email,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                # password_hash is stored as TEXT (bcrypt ASCII);
                # auth.py expects bytes for bcrypt.checkpw.
                return row[0].encode("utf-8")
        finally:
            put_connection(conn)

    # ------------------------------------------------------------------
    # courses
    # ------------------------------------------------------------------

    @property
    def courses(self):
        """Dict of all courses keyed by id.

        pages.py accesses ``store.courses.values()`` directly, so this
        property keeps that contract intact.
        """
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, title, instructor_id FROM courses")
                return {
                    row[0]: {
                        "id": row[0],
                        "title": row[1],
                        "instructorId": row[2],
                    }
                    for row in cur.fetchall()
                }
        finally:
            put_connection(conn)

    def create_user(self, email, password, role="STUDENT"):
        if self.get_user_by_email(email) is not None:
            return None
        user_id = f"u{len(self.users) + 1}"
        user = {
            "id": user_id,
            "email": email,
            "role": role,
            "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10)),
        }
        self.users[user_id] = user
        return self._public(user)

    def course_exists(self, cid):
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM courses WHERE id = %s", (cid,))
                return cur.fetchone() is not None
        finally:
            put_connection(conn)

    def get_course(self, cid):
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, title, instructor_id FROM courses WHERE id = %s",
                    (cid,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return {"id": row[0], "title": row[1], "instructorId": row[2]}
        finally:
            put_connection(conn)

    # ------------------------------------------------------------------
    # enrollments
    # ------------------------------------------------------------------

    def get_enrollment(self, cid, sid):
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT course_id, student_id, score "
                    "FROM enrollments "
                    "WHERE course_id = %s AND student_id = %s",
                    (cid, sid),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return {
                    "courseId": row[0],
                    "studentId": row[1],
                    "score": float(row[2]) if row[2] is not None else None,
                }
        finally:
            put_connection(conn)

    def get_grades(self, cid):
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT student_id, score "
                    "FROM enrollments "
                    "WHERE course_id = %s",
                    (cid,),
                )
                return [
                    {
                        "studentId": row[0],
                        "score": float(row[1]) if row[1] is not None else None,
                    }
                    for row in cur.fetchall()
                ]
        finally:
            put_connection(conn)

    def set_score(self, cid, sid, score):
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE enrollments SET score = %s "
                    "WHERE course_id = %s AND student_id = %s "
                    "RETURNING course_id, student_id, score",
                    (score, cid, sid),
                )
                row = cur.fetchone()
                conn.commit()
                if row is None:
                    return None
                return {
                    "courseId": row[0],
                    "studentId": row[1],
                    "score": float(row[2]) if row[2] is not None else None,
                }
        except Exception:
            conn.rollback()
            raise
        finally:
            put_connection(conn)

    def is_instructor_of(self, uid, cid):
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM courses "
                    "WHERE id = %s AND instructor_id = %s",
                    (cid, uid),
                )
                return cur.fetchone() is not None
        finally:
            put_connection(conn)
