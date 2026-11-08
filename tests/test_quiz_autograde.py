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


def test_answer_key_hidden_from_students(client):
    chi = token(client, "chi.sv@lms.test")
    an = token(client, "an.gv@lms.test")
    student_view = client.get("/courses/c1/quizzes/q1", headers=auth(chi))
    assert student_view.status_code == 200
    assert all("answerKey" not in q for q in student_view.json["questions"])
    teacher_view = client.get("/courses/c1/quizzes/q1", headers=auth(an))
    assert all(q["answerKey"] in "ABCDEF" for q in teacher_view.json["questions"])


def test_autograde_scores_on_submit(client):
    # chi has a seeded IN_PROGRESS attempt on q1 (key A,B,C; 1pt each).
    chi = token(client, "chi.sv@lms.test")
    saved = client.put(
        "/courses/c1/quizzes/q1/attempts/answers",
        headers=auth(chi),
        json={"answers": "A,B,C"},
    )
    assert saved.status_code == 200
    submitted = client.post(
        "/courses/c1/quizzes/q1/attempts/submit", headers=auth(chi), json={}
    )
    assert submitted.status_code == 200
    assert submitted.json["state"] == "SUBMITTED"
    assert submitted.json["score"] == 10.0


def test_autograde_partial_score(client):
    # dung on q2 (key A,C; 1pt each): one wrong answer halves the score.
    dung = token(client, "dung.sv@lms.test")
    started = client.post("/courses/c1/quizzes/q2/attempts", headers=auth(dung))
    assert started.status_code == 201
    submitted = client.post(
        "/courses/c1/quizzes/q2/attempts/submit",
        headers=auth(dung),
        json={"answers": "B,C"},
    )
    assert submitted.status_code == 200
    assert submitted.json["score"] == 5.0
    # Instructor can still confirm/override into GRADED.
    an = token(client, "an.gv@lms.test")
    graded = client.post(
        "/courses/c1/quizzes/q2/attempts/u5/grade",
        headers=auth(an),
        json={"score": 6},
    )
    assert graded.status_code == 200
    assert graded.json["state"] == "GRADED"
    assert graded.json["score"] == 6


def test_create_quiz_validation(client):
    an = token(client, "an.gv@lms.test")
    good = client.post(
        "/courses/c1/quizzes",
        headers=auth(an),
        json={
            "title": "Kiểm tra 15 phút",
            "timeMinutes": 15,
            "questions": [
                {"text": "1+1=?", "options": ["1", "2"], "answerIndex": 1, "points": 2}
            ],
        },
    )
    assert good.status_code == 201
    for bad_questions in (
        [{"text": "x", "options": ["chỉ 1"], "answerIndex": 0}],  # too few options
        [{"text": "x", "options": ["a", "b"], "answerIndex": 5}],  # index out of range
        [{"text": "x", "options": ["a", "b"], "answerIndex": "A"}],  # not an int
    ):
        response = client.post(
            "/courses/c1/quizzes",
            headers=auth(an),
            json={"title": "Sai", "questions": bad_questions},
        )
        assert response.status_code == 400
    assert client.post(
        "/courses/c1/quizzes",
        headers=auth(token(client, "chi.sv@lms.test")),
        json={"title": "Sneaky", "questions": [{"text": "x", "options": ["a", "b"], "answerIndex": 0}]},
    ).status_code == 403
