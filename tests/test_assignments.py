import io
from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from app.db import get_conn


@pytest.fixture
def client(tmp_path):
    app = create_app({
        "JWT_SECRET": "x" * 32,
        "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
        "UPLOAD_DIR": str(tmp_path / "uploads"),
    })
    return app.test_client()


def token(client, email, password="Lms@2026"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json["accessToken"]


def auth(token_value):
    return {"Authorization": f"Bearer {token_value}"}


def make_assignment(client, an, title="Essay tuần 1"):
    due = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    response = client.post(
        "/courses/c1/assignments",
        headers=auth(an),
        json={"title": title, "description": "Viết 500 từ", "dueAt": due},
    )
    assert response.status_code == 201
    return response.json["id"]


def submit(client, headers, aid, name="baitap.docx"):
    return client.post(
        f"/courses/c1/assignments/{aid}/submissions",
        headers=headers,
        data={"file": (io.BytesIO(b"PK fake docx"), name)},
        content_type="multipart/form-data",
    )


def force_expire(aid):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE assignments SET due_at = NOW() - INTERVAL '1 hour' WHERE id = %s",
                (aid,),
            )


def test_submit_and_resubmit_before_deadline(client):
    an = token(client, "an.gv@lms.test")
    chi = token(client, "chi.sv@lms.test")
    aid = make_assignment(client, an)

    first = submit(client, auth(chi), aid)
    assert first.status_code == 201
    second = submit(client, auth(chi), aid, name="baitap-v2.docx")
    assert second.status_code == 201

    rows = client.get(f"/courses/c1/assignments/{aid}/submissions", headers=auth(chi)).json
    assert len(rows) == 1
    assert rows[0]["originalName"] == "baitap-v2.docx"
    assert rows[0]["studentId"] == "u4"


def test_late_submission_rejected(client):
    an = token(client, "an.gv@lms.test")
    dung = token(client, "dung.sv@lms.test")
    aid = make_assignment(client, an)
    force_expire(aid)
    late = submit(client, auth(dung), aid)
    assert late.status_code == 409
    assert late.json["error"] == "DEADLINE_PASSED"


def test_submission_visibility_and_download(client):
    an = token(client, "an.gv@lms.test")
    chi = token(client, "chi.sv@lms.test")
    dung = token(client, "dung.sv@lms.test")
    em = token(client, "em.sv@lms.test")
    aid = make_assignment(client, an)
    submit(client, auth(chi), aid)

    mine = client.get(f"/courses/c1/assignments/{aid}/submissions", headers=auth(chi)).json
    assert [r["studentId"] for r in mine] == ["u4"]
    everyone = client.get(f"/courses/c1/assignments/{aid}/submissions", headers=auth(an)).json
    assert {r["studentId"] for r in everyone} == {"u4"}

    sub_id = mine[0]["id"]
    assert client.get(f"/assignments/submissions/{sub_id}/download", headers=auth(chi)).status_code == 200
    # Same-course student cannot fetch someone else's file; outsider cannot either.
    assert client.get(f"/assignments/submissions/{sub_id}/download", headers=auth(dung)).status_code == 403
    assert client.get(f"/assignments/submissions/{sub_id}/download", headers=auth(em)).status_code == 403


def test_grading_with_feedback(client):
    an = token(client, "an.gv@lms.test")
    chi = token(client, "chi.sv@lms.test")
    aid = make_assignment(client, an)
    submit(client, auth(chi), aid)

    graded = client.post(
        f"/courses/c1/assignments/{aid}/submissions/u4/grade",
        headers=auth(an),
        json={"score": 8.5, "feedback": "Bài làm tốt"},
    )
    assert graded.status_code == 200
    row = client.get(f"/courses/c1/assignments/{aid}/submissions", headers=auth(chi)).json[0]
    assert row["score"] == 8.5
    assert row["feedback"] == "Bài làm tốt"
    # Students cannot grade.
    assert client.post(
        f"/courses/c1/assignments/{aid}/submissions/u4/grade",
        headers=auth(chi),
        json={"score": 10},
    ).status_code == 403


def test_create_validation(client):
    an = token(client, "an.gv@lms.test")
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert client.post(
        "/courses/c1/assignments", headers=auth(an), json={"title": "Quá hạn", "dueAt": past}
    ).status_code == 400
