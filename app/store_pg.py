"""
store_pg.py – PostgreSQL implementation của Store interface.

Cung cấp cùng interface như store.py (Store cũ dùng seed.json)
nhưng mọi thao tác đọc/ghi đều qua PostgreSQL thông qua db.py.

Các bảng cần tồn tại (xem migrate.py):
    users, courses, enrollments
"""

from __future__ import annotations

import bcrypt

from .db import get_conn, get_cursor


class PgStore:
    """
    PostgreSQL-backed store thay thế Store (seed.json).

    Tất cả method đều tương thích với interface của Store cũ
    để phần còn lại của app không cần thay đổi.
    """

    # ------------------------------------------------------------------ #
    #  Helpers nội bộ                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _public(row: dict) -> dict:
        """Chỉ trả về các trường công khai của user (không có password_hash)."""
        return {"id": row["id"], "email": row["email"], "role": row["role"]}

    # ------------------------------------------------------------------ #
    #  User queries                                                        #
    # ------------------------------------------------------------------ #

    def get_user_by_email(self, email: str) -> dict | None:
        """Tra cứu user theo email, trả về dict công khai hoặc None."""
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    "SELECT id, email, role FROM users WHERE email = %s LIMIT 1",
                    (email,),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, uid: str) -> dict | None:
        """Tra cứu user theo id, trả về dict công khai hoặc None."""
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    "SELECT id, email, role FROM users WHERE id = %s LIMIT 1",
                    (uid,),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def get_password_hash_by_email(self, email: str) -> bytes | None:
        """Trả về password_hash (bytes) của user theo email, hoặc None."""
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    "SELECT password_hash FROM users WHERE email = %s LIMIT 1",
                    (email,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        val = row["password_hash"]
        # Cột TEXT → psycopg2 trả về str; chuẩn hoá thành bytes cho bcrypt.checkpw
        if isinstance(val, str):
            return val.encode("utf-8")
        return bytes(val) if isinstance(val, (memoryview, bytearray)) else val

    def create_user(
        self,
        uid: str,
        email: str,
        password: str,
        role: str = "STUDENT",
    ) -> dict:
        """
        Tạo user mới, hash password bằng bcrypt trước khi lưu.

        Returns:
            dict công khai của user vừa tạo.
        Raises:
            psycopg2.errors.UniqueViolation nếu email đã tồn tại.
        """
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10))
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO users (id, email, password_hash, role)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, email, role
                    """,
                    (uid, email, pw_hash, role),
                )
                row = cur.fetchone()
        return dict(row)

    def update_password(self, uid: str, new_password: str) -> bool:
        """
        Cập nhật mật khẩu cho user theo id.

        Returns:
            True nếu cập nhật thành công, False nếu user không tồn tại.
        """
        pw_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt(rounds=10))
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    "UPDATE users SET password_hash = %s WHERE id = %s",
                    (pw_hash, uid),
                )
                return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    #  Course queries                                                      #
    # ------------------------------------------------------------------ #

    def course_exists(self, cid: str) -> bool:
        """Kiểm tra khoá học có tồn tại không."""
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    "SELECT 1 FROM courses WHERE id = %s LIMIT 1", (cid,)
                )
                return cur.fetchone() is not None

    def get_course(self, cid: str) -> dict | None:
        """Trả về thông tin khoá học hoặc None."""
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    "SELECT id, title, instructor_id AS \"instructorId\" FROM courses WHERE id = %s LIMIT 1",
                    (cid,),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def get_all_courses(self) -> list[dict]:
        """Trả về danh sách tất cả khoá học."""
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    'SELECT id, title, instructor_id AS "instructorId" FROM courses ORDER BY id'
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def is_instructor_of(self, uid: str, cid: str) -> bool:
        """Kiểm tra uid có phải instructor của khoá học cid không."""
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    "SELECT 1 FROM courses WHERE id = %s AND instructor_id = %s LIMIT 1",
                    (cid, uid),
                )
                return cur.fetchone() is not None

    # ------------------------------------------------------------------ #
    #  Enrollment / grade queries                                          #
    # ------------------------------------------------------------------ #

    def get_enrollment(self, cid: str, sid: str) -> dict | None:
        """Trả về enrollment (courseId, studentId, score) hoặc None."""
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    SELECT course_id AS "courseId", student_id AS "studentId",
                           score::float8 AS score
                    FROM enrollments
                    WHERE course_id = %s AND student_id = %s
                    LIMIT 1
                    """,
                    (cid, sid),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def get_grades(self, cid: str) -> list[dict]:
        """Trả về danh sách {studentId, score} của khoá học."""
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    SELECT student_id AS "studentId", score::float8 AS score
                    FROM enrollments
                    WHERE course_id = %s
                    ORDER BY student_id
                    """,
                    (cid,),
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def set_score(self, cid: str, sid: str, score: float) -> dict | None:
        """
        Cập nhật điểm của sinh viên trong khoá học.

        Returns:
            dict enrollment đã cập nhật, hoặc None nếu không tìm thấy.
        """
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    UPDATE enrollments
                    SET score = %s
                    WHERE course_id = %s AND student_id = %s
                    RETURNING course_id AS "courseId", student_id AS "studentId",
                              score::float8 AS score
                    """,
                    (score, cid, sid),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------ #
    #  Compatibility shim: thuộc tính .courses cho pages.py               #
    # ------------------------------------------------------------------ #

    @property
    def courses(self) -> dict:
        """
        Trả về dict {id: course} để tương thích với code dùng store.courses.values().
        Lưu ý: mỗi lần truy cập thực hiện 1 query. Tránh gọi nhiều lần trong loop.
        """
        return {c["id"]: c for c in self.get_all_courses()}
