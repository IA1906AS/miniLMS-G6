"""
store_pg.py – PostgreSQL implementation của Store interface.

Cung cấp cùng interface như store.py (Store cũ dùng seed.json)
nhưng mọi thao tác đọc/ghi đều qua PostgreSQL thông qua db.py.

Các bảng cần tồn tại (xem db_init.py):
    users, courses, enrollments
"""

from __future__ import annotations

from uuid import uuid4

import bcrypt
from psycopg2 import errors as pg_errors

from .db import get_conn, get_cursor
from .errors import CodeExists, Conflict, DeadlinePassed, InvalidAttemptState


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
                    """
                    SELECT id, email, role, full_name, bio, phone,
                           avatar_path, locked
                    FROM users WHERE email = %s LIMIT 1
                    """,
                    (email,),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, uid: str) -> dict | None:
        """Tra cứu user theo id, trả về dict công khai hoặc None."""
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    SELECT id, email, role, full_name, bio, phone,
                           avatar_path, locked
                    FROM users WHERE id = %s LIMIT 1
                    """,
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
                    (pw_hash.decode("utf-8"), uid),
                )
                return cur.rowcount > 0

    @staticmethod
    def _member_public(row: dict) -> dict:
        out = {
            "id": row["id"],
            "email": row["email"],
            "role": row["role"],
            "fullName": row["full_name"],
        }
        out["avatarUrl"] = (
            f"/files/avatars/{row['avatar_path']}" if row.get("avatar_path") else None
        )
        return out

    def update_user_profile(self, uid: str, full_name: str, bio: str, phone: str) -> bool:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    "UPDATE users SET full_name = %s, bio = %s, phone = %s "
                    "WHERE id = %s",
                    (full_name, bio, phone, uid),
                )
                return cur.rowcount > 0

    def set_avatar(self, uid: str, stored_name: str) -> bool:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    "UPDATE users SET avatar_path = %s WHERE id = %s",
                    (stored_name, uid),
                )
                return cur.rowcount > 0

    def list_users(self, q: str | None = None) -> list[dict]:
        sql = (
            "SELECT id, email, role, full_name, avatar_path, locked "
            "FROM users"
        )
        params: tuple = ()
        if q:
            like = f"%{q}%"
            sql += " WHERE email ILIKE %s OR full_name ILIKE %s"
            params = (like, like)
        sql += " ORDER BY id"
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        out = []
        for r in rows:
            member = self._member_public(dict(r))
            member["locked"] = bool(r["locked"])
            out.append(member)
        return out

    def list_course_members(self, cid: str) -> list[dict]:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    SELECT id, email, role, full_name, avatar_path
                    FROM users
                    WHERE id = (SELECT instructor_id FROM courses WHERE id = %s)
                       OR id IN (SELECT student_id FROM enrollments WHERE course_id = %s)
                    ORDER BY role, id
                    """,
                    (cid, cid),
                )
                rows = cur.fetchall()
        return [self._member_public(dict(r)) for r in rows]

    def set_user_lock(self, uid: str, locked: bool) -> bool:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    "UPDATE users SET locked = %s WHERE id = %s", (locked, uid)
                )
                return cur.rowcount > 0

    def set_user_role(self, uid: str, role: str) -> bool:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    "UPDATE users SET role = %s WHERE id = %s", (role, uid)
                )
                return cur.rowcount > 0

    def delete_user_avatar(self, uid: str) -> str | None:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    UPDATE users SET avatar_path = NULL
                    WHERE id = %s AND avatar_path IS NOT NULL
                    RETURNING avatar_path
                    """,
                    (uid,),
                )
                row = cur.fetchone()
        return dict(row)["avatar_path"] if row else None

    # ------------------------------------------------------------------ #
    #  Password reset OTP                                                  #
    # ------------------------------------------------------------------ #

    def purge_expired_reset_otps(self) -> None:
        """Xoá mọi OTP đã hết hạn (5 phút theo thiết kế)."""
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute("DELETE FROM password_resets WHERE expires_at <= NOW()")

    def save_reset_otp(self, email: str, otp_hash: bytes, ttl_seconds: int) -> None:
        """Lưu (ghi đè) OTP reset cho email, hết hạn sau ttl_seconds."""
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO password_resets (email, otp_hash, expires_at)
                    VALUES (%s, %s, NOW() + make_interval(secs => %s))
                    ON CONFLICT (email) DO UPDATE
                    SET otp_hash = EXCLUDED.otp_hash,
                        expires_at = EXCLUDED.expires_at
                    """,
                    (email, otp_hash.decode("utf-8"), ttl_seconds),
                )

    def get_reset_otp_hash(self, email: str) -> bytes | None:
        """Trả về otp_hash còn hiệu lực, hoặc None."""
        self.purge_expired_reset_otps()
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    "SELECT otp_hash FROM password_resets WHERE email = %s",
                    (email,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        val = row["otp_hash"]
        return val.encode("utf-8") if isinstance(val, str) else bytes(val)

    def delete_reset_otp(self, email: str) -> None:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute("DELETE FROM password_resets WHERE email = %s", (email,))

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
                    """
                    SELECT id, title, instructor_id AS "instructorId", code
                    FROM courses WHERE id = %s LIMIT 1
                    """,
                    (cid,),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def get_all_courses(self) -> list[dict]:
        """Trả về danh sách tất cả khoá học."""
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    SELECT id, title, instructor_id AS "instructorId", code
                    FROM courses ORDER BY id
                    """
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

    def search_courses(
        self,
        q: str | None = None,
        instructor_id: str | None = None,
        enrolled_of: str | None = None,
    ) -> list[dict]:
        sql = (
            'SELECT c.id, c.title, c.instructor_id AS "instructorId", c.code '
            "FROM courses c"
        )
        where: list[str] = []
        params: list = []
        if q:
            where.append("c.title ILIKE %s")
            params.append(f"%{q}%")
        if instructor_id:
            where.append("c.instructor_id = %s")
            params.append(instructor_id)
        if enrolled_of:
            where.append(
                "c.id IN (SELECT course_id FROM enrollments WHERE student_id = %s)"
            )
            params.append(enrolled_of)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY c.id"
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def create_course(
        self, title: str, instructor_id: str, code: str
    ) -> dict:
        try:
            with get_conn() as conn:
                with get_cursor(conn) as cur:
                    cur.execute(
                        """
                        INSERT INTO courses (id, title, instructor_id, code)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id, title,
                                  instructor_id AS "instructorId", code
                        """,
                        (uuid4().hex, title, instructor_id, code),
                    )
                    row = cur.fetchone()
        except pg_errors.UniqueViolation as exc:
            raise CodeExists() from exc
        return dict(row)

    def update_course(self, cid: str, title: str, code: str) -> dict | None:
        try:
            with get_conn() as conn:
                with get_cursor(conn) as cur:
                    cur.execute(
                        """
                        UPDATE courses SET title = %s, code = %s
                        WHERE id = %s
                        RETURNING id, title,
                                  instructor_id AS "instructorId", code
                        """,
                        (title, code, cid),
                    )
                    row = cur.fetchone()
        except pg_errors.UniqueViolation as exc:
            raise CodeExists() from exc
        return dict(row) if row else None

    def get_course_by_code(self, code: str) -> dict | None:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    SELECT id, title, instructor_id AS "instructorId", code
                    FROM courses WHERE code = %s LIMIT 1
                    """,
                    (code,),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def add_enrollment(self, cid: str, sid: str) -> dict:
        try:
            with get_conn() as conn:
                with get_cursor(conn) as cur:
                    cur.execute(
                        """
                        INSERT INTO enrollments (course_id, student_id)
                        VALUES (%s, %s)
                        RETURNING course_id AS "courseId",
                                  student_id AS "studentId", score::float8 AS score
                        """,
                        (cid, sid),
                    )
                    row = cur.fetchone()
        except pg_errors.UniqueViolation as exc:
            raise Conflict("Sinh viên đã ghi danh khoá học này") from exc
        return dict(row)

    def delete_course(self, cid: str) -> bool:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                # enrollments and quiz_attempts predate ON DELETE CASCADE
                cur.execute("DELETE FROM quiz_attempts WHERE course_id = %s", (cid,))
                cur.execute("DELETE FROM enrollments WHERE course_id = %s", (cid,))
                cur.execute("DELETE FROM courses WHERE id = %s", (cid,))
                return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    #  Materials                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _material_public(row: dict) -> dict:
        out = {
            "id": row["id"],
            "courseId": row["course_id"],
            "uploaderId": row["uploader_id"],
            "originalName": row["original_name"],
            "sizeBytes": int(row["size_bytes"]),
            "createdAt": row["created_at"].isoformat(),
            "downloadUrl": f"/materials/{row['id']}/download",
        }
        return out

    def create_material(
        self,
        cid: str,
        uploader_id: str,
        original_name: str,
        stored_name: str,
        size_bytes: int,
    ) -> dict:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    INSERT INTO materials
                        (id, course_id, uploader_id, original_name,
                         stored_name, size_bytes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, course_id, uploader_id, original_name,
                              stored_name, size_bytes, created_at
                    """,
                    (uuid4().hex, cid, uploader_id, original_name,
                     stored_name, size_bytes),
                )
                row = cur.fetchone()
        return self._material_public(dict(row))

    def list_materials(self, cid: str) -> list[dict]:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    SELECT id, course_id, uploader_id, original_name,
                           stored_name, size_bytes, created_at
                    FROM materials WHERE course_id = %s
                    ORDER BY created_at DESC, id
                    """,
                    (cid,),
                )
                rows = cur.fetchall()
        return [self._material_public(dict(r)) for r in rows]

    def get_material(self, mid: str) -> dict | None:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    SELECT id, course_id, uploader_id, original_name,
                           stored_name, size_bytes, created_at
                    FROM materials WHERE id = %s LIMIT 1
                    """,
                    (mid,),
                )
                row = cur.fetchone()
        return self._material_public(dict(row)) if row else None

    def delete_material(self, mid: str) -> dict | None:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    DELETE FROM materials WHERE id = %s
                    RETURNING course_id, uploader_id, stored_name
                    """,
                    (mid,),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def get_material_file(self, mid: str) -> dict | None:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    SELECT course_id, uploader_id, original_name, stored_name
                    FROM materials WHERE id = %s LIMIT 1
                    """,
                    (mid,),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------ #
    #  Enrollment / grade queries                                          #
    # ------------------------------------------------------------------ #

    def get_enrollment(self, cid: str, sid: str) -> dict | None:
        """Trả về enrollment (courseId, studentId, score, version) hoặc None."""
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    SELECT course_id AS "courseId", student_id AS "studentId",
                           score::float8 AS score, version
                    FROM enrollments
                    WHERE course_id = %s AND student_id = %s
                    LIMIT 1
                    """,
                    (cid, sid),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def get_grades(self, cid: str, include_version: bool = False) -> list[dict]:
        """Trả về danh sách {studentId, score[, version]} của khoá học."""
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                if include_version:
                    cur.execute(
                        """
                        SELECT student_id AS "studentId", score::float8 AS score, version
                        FROM enrollments
                        WHERE course_id = %s
                        ORDER BY student_id
                        """,
                        (cid,),
                    )
                else:
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

    def set_score(
        self,
        cid: str,
        sid: str,
        score: float,
        version: int,
    ) -> dict | None:
        """
        Cập nhật điểm của sinh viên trong khoá học với Optimistic Locking.

        Bắt buộc truyền version (int):
            UPDATE enrollments SET score = %s, version = version + 1
            WHERE course_id = %s AND student_id = %s AND version = %s
        Nếu rowcount = 0 thì ném Conflict (HTTP 409).
        """
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    UPDATE enrollments
                    SET score = %s, version = version + 1
                    WHERE course_id = %s AND student_id = %s AND version = %s
                    RETURNING course_id AS "courseId", student_id AS "studentId",
                              score::float8 AS score, version
                    """,
                    (score, cid, sid, version),
                )
                row = cur.fetchone()
                if row is None:
                    # Phân biệt giữa 404 (không tìm thấy enrollment) và 409 (xung đột version)
                    cur.execute(
                        "SELECT 1 FROM enrollments WHERE course_id = %s AND student_id = %s",
                        (cid, sid),
                    )
                    if cur.fetchone() is None:
                        return None
                    raise Conflict("Điểm đã bị thay đổi bởi người khác, vui lòng tải lại")
                return dict(row)

    @staticmethod
    def _attempt_public(row: dict) -> dict:
        return {
            "id": row["id"],
            "courseId": row["course_id"],
            "quizId": row["quiz_id"],
            "studentId": row["student_id"],
            "answers": row["answers"],
            "score": float(row["score"]) if row["score"] is not None else None,
            "state": row["state"],
            "deadline": row["deadline"].isoformat(),
        }

    def get_attempt(self, cid: str, quiz: str, sid: str) -> dict | None:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    SELECT id, course_id, quiz_id, student_id, answers,
                           score, state, deadline
                    FROM quiz_attempts
                    WHERE course_id = %s AND quiz_id = %s AND student_id = %s
                    LIMIT 1
                    """,
                    (cid, quiz, sid),
                )
                row = cur.fetchone()
        return self._attempt_public(dict(row)) if row else None

    def list_attempts(self, cid: str, quiz: str) -> list[dict]:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    "SELECT id, course_id, quiz_id, student_id, answers, "
                    "score, state, deadline FROM quiz_attempts "
                    "WHERE course_id = %s AND quiz_id = %s ORDER BY student_id",
                    (cid, quiz),
                )
                rows = cur.fetchall()
        return [self._attempt_public(dict(r)) for r in rows]

    def _attempt_state(self, cid: str, quiz: str, sid: str) -> dict | None:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    SELECT state, deadline FROM quiz_attempts
                    WHERE course_id = %s AND quiz_id = %s AND student_id = %s
                    """,
                    (cid, quiz, sid),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def start_attempt(
        self, cid: str, quiz: str, sid: str, deadline
    ) -> dict:
        try:
            with get_conn() as conn:
                with get_cursor(conn) as cur:
                    cur.execute(
                        """
                        INSERT INTO quiz_attempts
                            (id, course_id, quiz_id, student_id, answers, state, deadline)
                        VALUES (%s, %s, %s, %s, '', 'IN_PROGRESS', %s)
                        RETURNING id, course_id, quiz_id, student_id, answers,
                                  score, state, deadline
                        """,
                        (uuid4().hex, cid, quiz, sid, deadline),
                    )
                    row = cur.fetchone()
        except pg_errors.UniqueViolation as exc:
            raise InvalidAttemptState(
                "Sinh viên này đã có lượt làm bài cho quiz"
            ) from exc
        return self._attempt_public(dict(row))

    def save_answers(
        self, cid: str, quiz: str, sid: str, answers: str, *, from_state: str
    ) -> dict:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    UPDATE quiz_attempts
                    SET answers = %s, updated_at = NOW()
                    WHERE course_id = %s AND quiz_id = %s AND student_id = %s
                      AND state = %s
                    RETURNING id, course_id, quiz_id, student_id, answers,
                              score, state, deadline
                    """,
                    (answers, cid, quiz, sid, from_state),
                )
                row = cur.fetchone()
        if row is None:
            current = self._attempt_state(cid, quiz, sid)
            if current is None:
                return None
            raise InvalidAttemptState(
                f"Không thể sửa bài ở trạng thái {current['state']}"
            )
        return self._attempt_public(dict(row))

    def submit_attempt(
        self,
        cid: str,
        quiz: str,
        sid: str,
        answers: str,
        *,
        from_state: str,
        to_state: str,
    ) -> dict:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    UPDATE quiz_attempts
                    SET answers = %s, state = %s, updated_at = NOW()
                    WHERE course_id = %s AND quiz_id = %s AND student_id = %s
                      AND state = %s AND NOW() <= deadline
                    RETURNING id, course_id, quiz_id, student_id, answers,
                              score, state, deadline
                    """,
                    (answers, to_state, cid, quiz, sid, from_state),
                )
                row = cur.fetchone()
        if row is None:
            current = self._attempt_state(cid, quiz, sid)
            if current is None:
                return None
            if current["state"] != from_state:
                raise InvalidAttemptState(
                    f"Không thể nộp bài ở trạng thái {current['state']}"
                )
            raise DeadlinePassed()
        return self._attempt_public(dict(row))

    def grade_attempt(
        self,
        cid: str,
        quiz: str,
        sid: str,
        score: float,
        *,
        from_state: str,
        to_state: str,
    ) -> dict:
        with get_conn() as conn:
            with get_cursor(conn) as cur:
                cur.execute(
                    """
                    UPDATE quiz_attempts
                    SET score = %s, state = %s, updated_at = NOW()
                    WHERE course_id = %s AND quiz_id = %s AND student_id = %s
                      AND state = %s
                    RETURNING id, course_id, quiz_id, student_id, answers,
                              score, state, deadline
                    """,
                    (score, to_state, cid, quiz, sid, from_state),
                )
                row = cur.fetchone()
        if row is None:
            current = self._attempt_state(cid, quiz, sid)
            if current is None:
                return None
            raise InvalidAttemptState(
                f"Không thể chấm bài ở trạng thái {current['state']}"
            )
        return self._attempt_public(dict(row))

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
