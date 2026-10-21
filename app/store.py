import json
from pathlib import Path

import bcrypt

SEED_PATH = Path(__file__).resolve().parent.parent / "seed.json"


class Store:
    def __init__(self):
        with open(SEED_PATH, encoding="utf-8") as f:
            seed = json.load(f)

        self.users = {
            u["id"]: {
                "id": u["id"],
                "email": u["email"],
                "role": u["role"],
                "password_hash": bcrypt.hashpw(
                    u["password"].encode(), bcrypt.gensalt(rounds=10)
                ),
            }
            for u in seed["users"]
        }
        self.courses = {c["id"]: c for c in seed["courses"]}
        self.enrollments = list(seed["enrollments"])

    def _public(self, u):
        return {"id": u["id"], "email": u["email"], "role": u["role"]}

    def get_user_by_email(self, email):
        for u in self.users.values():
            if u["email"] == email:
                return self._public(u)
        return None

    def get_user_by_id(self, uid):
        u = self.users.get(uid)
        return self._public(u) if u else None

    def get_password_hash_by_email(self, email):
        for u in self.users.values():
            if u["email"] == email:
                return u["password_hash"]
        return None

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
        return cid in self.courses

    def get_course(self, cid):
        return self.courses.get(cid)

    def get_enrollment(self, cid, sid):
        return next(
            (e for e in self.enrollments if e["courseId"] == cid and e["studentId"] == sid),
            None,
        )

    def get_grades(self, cid):
        return [
            {"studentId": e["studentId"], "score": e["score"]}
            for e in self.enrollments
            if e["courseId"] == cid
        ]

    def set_score(self, cid, sid, score):
        e = self.get_enrollment(cid, sid)
        if e is None:
            return None
        e["score"] = score
        return e

    def is_instructor_of(self, uid, cid):
        c = self.courses.get(cid)
        return c is not None and c["instructorId"] == uid
