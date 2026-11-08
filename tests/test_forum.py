import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app({
        "JWT_SECRET": "x" * 32,
        "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
    })
    return app.test_client()


def token(client, email, password="Lms@2026"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json["accessToken"]


def auth(token_value):
    return {"Authorization": f"Bearer {token_value}"}


def test_topic_author_only_edit_delete(client):
    chi = token(client, "chi.sv@lms.test")
    dung = token(client, "dung.sv@lms.test")
    an = token(client, "an.gv@lms.test")

    made = client.post(
        "/courses/c1/topics", headers=auth(chi), json={"title": "Thắc mắc đề tài", "body": "Em chưa rõ yêu cầu"}
    )
    assert made.status_code == 201
    tid = made.json["id"]

    # Even the course instructor is not the author.
    assert client.put(f"/topics/{tid}", headers=auth(an), json={"body": "sửa"}).status_code == 403
    assert client.put(f"/topics/{tid}", headers=auth(dung), json={"body": "sửa"}).status_code == 403
    assert client.put(
        f"/topics/{tid}", headers=auth(chi), json={"title": "Thắc mắc đề tài (đã sửa)", "body": "Rồi ạ"}
    ).status_code == 200
    assert client.delete(f"/topics/{tid}", headers=auth(dung)).status_code == 403
    assert client.delete(f"/topics/{tid}", headers=auth(chi)).status_code == 200


def test_comments_flow(client):
    chi = token(client, "chi.sv@lms.test")
    dung = token(client, "dung.sv@lms.test")

    listed = client.get("/courses/c1/topics", headers=auth(chi)).json
    assert any(t["id"] == "t1" for t in listed)

    wrote = client.post("/topics/t1/comments", headers=auth(dung), json={"body": "Mình cũng thắc mắc"}
    )
    assert wrote.status_code == 201
    cid = wrote.json["id"]
    assert client.put(f"/comments/{cid}", headers=auth(chi), json={"body": "không phải của mình"}
    ).status_code == 403
    assert client.put(f"/comments/{cid}", headers=auth(dung), json={"body": "Cảm ơn thầy"}
    ).status_code == 200
    assert client.delete(f"/comments/{cid}", headers=auth(chi)).status_code == 403
    assert client.delete(f"/comments/{cid}", headers=auth(dung)).status_code == 200


def test_outsider_cannot_read_course_forum(client):
    em = token(client, "em.sv@lms.test")  # enrolled in c2 only
    assert client.get("/courses/c1/topics", headers=auth(em)).status_code == 403
    assert client.get("/topics/t1", headers=auth(em)).status_code == 403


def test_announcements_instructor_only_and_stubbed_email(client):
    an = token(client, "an.gv@lms.test")
    chi = token(client, "chi.sv@lms.test")
    em = token(client, "em.sv@lms.test")

    posted = client.post(
        "/courses/c1/announcements",
        headers=auth(an),
        json={"title": "Nghỉ học tuần này", "body": "Tự học chương 4"},
    )
    assert posted.status_code == 201
    assert posted.json["emailQueued"] is True
    assert client.post(
        "/courses/c1/announcements", headers=auth(chi), json={"title": "x", "body": "y"}
    ).status_code == 403

    rows = client.get("/courses/c1/announcements", headers=auth(chi)).json
    assert {r["title"] for r in rows} >= {"Nghỉ học tuần này"}
    assert client.get("/courses/c1/announcements", headers=auth(em)).status_code == 403
