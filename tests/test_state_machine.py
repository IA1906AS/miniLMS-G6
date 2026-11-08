import pytest

from app import create_app
from app.attempt_sm import (
    GRADED,
    IN_PROGRESS,
    SUBMITTED,
    transition,
)
from app.auth import create_token
from app.errors import InvalidAttemptState


@pytest.fixture
def app(tmp_path):
    return create_app({
        "JWT_SECRET": "p7-state-machine-test-secret-32-characters",
        "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
    })


@pytest.fixture
def client(app):
    return app.test_client()


def auth(app, uid):
    with app.app_context():
        return {"Authorization": f"Bearer {create_token(uid)}"}


def test_transition_table_only_allows_the_documented_edges():
    assert transition(IN_PROGRESS, "SAVE") == IN_PROGRESS
    assert transition(IN_PROGRESS, "SUBMIT") == SUBMITTED
    assert transition(SUBMITTED, "GRADE") == GRADED
    for state, action in (
        (SUBMITTED, "SAVE"),
        (SUBMITTED, "SUBMIT"),
        (GRADED, "SAVE"),
        (GRADED, "SUBMIT"),
        (GRADED, "GRADE"),
    ):
        with pytest.raises(InvalidAttemptState):
            transition(state, action)


def test_happy_path_walks_the_full_state_machine(client, app):
    chi, an = auth(app, "u4"), auth(app, "u2")

    started = client.post("/courses/c1/quizzes/q2/attempts", headers=chi)
    assert started.status_code == 201
    assert started.json["state"] == IN_PROGRESS

    saved = client.put(
        "/courses/c1/quizzes/q2/attempts/answers",
        headers=chi,
        json={"answers": "A,B"},
    )
    assert saved.status_code == 200
    assert saved.json["answers"] == "A,B"
    assert saved.json["state"] == IN_PROGRESS

    submitted = client.post(
        "/courses/c1/quizzes/q2/attempts/submit",
        headers=chi,
        json={"answers": "A,C"},
    )
    assert submitted.status_code == 200
    assert submitted.json["state"] == SUBMITTED
    assert submitted.json["answers"] == "A,C"

    graded = client.post(
        "/courses/c1/quizzes/q2/attempts/u4/grade",
        headers=an,
        json={"score": 8.5},
    )
    assert graded.status_code == 200
    assert graded.json["state"] == GRADED
    assert graded.json["score"] == 8.5

    assert client.post(
        "/courses/c1/quizzes/q2/attempts/submit", headers=chi, json={"answers": "A"}
    ).json["error"] == "INVALID_ATTEMPT_STATE"
    assert client.put(
        "/courses/c1/quizzes/q2/attempts/answers", headers=chi, json={"answers": "A"}
    ).json["error"] == "INVALID_ATTEMPT_STATE"
    assert client.post(
        "/courses/c1/quizzes/q2/attempts/u4/grade", headers=an, json={"score": 9}
    ).json["error"] == "INVALID_ATTEMPT_STATE"


def test_submit_without_start_is_rejected_and_creates_nothing(client, app):
    chi = auth(app, "u4")
    response = client.post(
        "/courses/c1/quizzes/q9/attempts/submit",
        headers=chi,
        json={"answers": "A,B,C"},
    )
    assert response.status_code == 404
    assert response.json["error"] == "NOT_FOUND"
    listed = client.get("/courses/c1/quizzes/q9/attempts", headers=chi)
    assert listed.status_code == 200
    assert listed.json == []


def test_submitted_attempt_cannot_be_edited_or_resubmitted(client, app):
    dung = auth(app, "u5")
    edited = client.put(
        "/courses/c1/quizzes/q1/attempts/answers",
        headers=dung,
        json={"answers": "đáp án mới sau khi nộp"},
    )
    assert edited.status_code == 409
    assert edited.json["error"] == "INVALID_ATTEMPT_STATE"
    resubmitted = client.post(
        "/courses/c1/quizzes/q1/attempts/submit",
        headers=dung,
        json={"answers": "A,B,C"},
    )
    assert resubmitted.status_code == 409
    assert resubmitted.json["error"] == "INVALID_ATTEMPT_STATE"
    row = client.get("/courses/c1/quizzes/q1/attempts", headers=dung).json[0]
    assert row["answers"] == "A,B,C"


def test_submit_after_deadline_is_rejected(client, app):
    em = auth(app, "u6")
    response = client.post(
        "/courses/c2/quizzes/q1/attempts/submit",
        headers=em,
        json={"answers": "A,C,B"},
    )
    assert response.status_code == 409
    assert response.json["error"] == "DEADLINE_PASSED"
    row = client.get("/courses/c2/quizzes/q1/attempts", headers=em).json[0]
    assert row["state"] == IN_PROGRESS


def test_start_twice_is_rejected(client, app):
    chi = auth(app, "u4")
    response = client.post("/courses/c1/quizzes/q1/attempts", headers=chi)
    assert response.status_code == 409
    assert response.json["error"] == "INVALID_ATTEMPT_STATE"


def test_grade_before_submit_is_rejected(client, app):
    an = auth(app, "u2")
    response = client.post(
        "/courses/c1/quizzes/q1/attempts/u4/grade",
        headers=an,
        json={"score": 9},
    )
    assert response.status_code == 409
    assert response.json["error"] == "INVALID_ATTEMPT_STATE"


def test_attempt_authorization_boundaries(client, app):
    chi, binh, admin, em = (
        auth(app, "u4"),
        auth(app, "u3"),
        auth(app, "u1"),
        auth(app, "u6"),
    )

    assert client.post(
        "/courses/c1/quizzes/q1/attempts/u4/grade", headers=chi, json={"score": 9}
    ).status_code == 403
    assert client.post(
        "/courses/c1/quizzes/q1/attempts/u4/grade", headers=binh, json={"score": 9}
    ).status_code == 403
    assert client.post(
        "/courses/c1/quizzes/q1/attempts", headers=em
    ).status_code == 403
    assert client.post(
        "/courses/c1/quizzes/q1/attempts/submit",
        headers=None,
        json={"answers": "A"},
    ).status_code == 401

    listed = client.get("/courses/c1/quizzes/q1/attempts", headers=chi).json
    assert [row["studentId"] for row in listed] == ["u4"]
    all_rows = client.get("/courses/c1/quizzes/q1/attempts", headers=admin).json
    assert [row["studentId"] for row in all_rows] == ["u4", "u5"]


def test_attempt_input_validation(client, app):
    chi = auth(app, "u4")
    assert client.put(
        "/courses/c1/quizzes/q1/attempts/answers", headers=chi, json={"answers": "   "}
    ).status_code == 400
    assert client.put(
        "/courses/c1/quizzes/q1/attempts/answers", headers=chi, json={"answers": 42}
    ).status_code == 400
    an = auth(app, "u2")
    assert client.post(
        "/courses/c1/quizzes/q1/attempts/u5/grade", headers=an, json={"score": 11}
    ).status_code == 400
