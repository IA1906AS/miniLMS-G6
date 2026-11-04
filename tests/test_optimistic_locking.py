import pytest

from app import create_app

SECRET = "s" * 32


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            "JWT_SECRET": SECRET,
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
        }
    )


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, email, password="Lms@2026"):
    return client.post("/auth/login", json={"email": email, "password": password})


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def token(client, email):
    r = login(client, email)
    assert r.status_code == 200
    return r.get_json()["accessToken"]


def test_optimistic_locking_concurrent_edit_conflict(client):
    """
    Mô phỏng 2 người cùng sửa một điểm:
    - Cả 2 cùng đọc điểm ban đầu (score=7.5, version=1).
    - Người 1 lưu trước với version=1 -> thành công (score=8.5, version=2).
    - Người 2 lưu sau vẫn gửi version=1 -> bị từ chối với HTTP 409 Conflict.
    - Người 2 đọc lại điểm mới (score=8.5, version=2), gửi lại với version=2 -> thành công.
    """
    an = token(client, "an.gv@lms.test")
    headers = auth(an)

    # 1. Đọc điểm ban đầu
    read_resp = client.get("/courses/c1/grades/u4", headers=headers)
    assert read_resp.status_code == 200
    grade_data = read_resp.get_json()
    assert grade_data["score"] == 7.5
    assert grade_data["version"] == 1

    # Mô phỏng: Cả 2 người dùng (hoặc 2 tab) cùng nhận được version = 1
    user1_cached_version = grade_data["version"]  # 1
    user2_cached_version = grade_data["version"]  # 1

    # 2. Người 1 lưu trước (sửa thành 8.5) với version = 1
    resp1 = client.put(
        "/courses/c1/grades/u4",
        headers=headers,
        json={"score": 8.5, "version": user1_cached_version},
    )
    assert resp1.status_code == 200
    body1 = resp1.get_json()
    assert body1["score"] == 8.5
    assert body1["version"] == 2

    # 3. Người 2 lưu sau (muốn sửa thành 9.0) nhưng vẫn giữ version cũ = 1
    resp2 = client.put(
        "/courses/c1/grades/u4",
        headers=headers,
        json={"score": 9.0, "version": user2_cached_version},
    )
    # Bị từ chối HTTP 409 Conflict
    assert resp2.status_code == 409
    body2 = resp2.get_json()
    assert body2["error"] == "CONFLICT"
    assert body2["message"] == "Điểm đã bị thay đổi bởi người khác, vui lòng tải lại"

    # 4. Người 2 tải lại dữ liệu mới nhất (thấy điểm 8.5 và version 2)
    reload_resp = client.get("/courses/c1/grades/u4", headers=headers)
    assert reload_resp.status_code == 200
    reloaded_data = reload_resp.get_json()
    assert reloaded_data["score"] == 8.5
    assert reloaded_data["version"] == 2

    # 5. Người 2 sửa lại thành 9.0 với version mới = 2 -> Thành công
    resp2_retry = client.put(
        "/courses/c1/grades/u4",
        headers=headers,
        json={"score": 9.0, "version": reloaded_data["version"]},
    )
    assert resp2_retry.status_code == 200
    retry_body = resp2_retry.get_json()
    assert retry_body["score"] == 9.0
    assert retry_body["version"] == 3


def test_get_course_grades_returns_version_for_instructor(client):
    """Giảng viên khi xem danh sách điểm nhận được trường version của từng sinh viên."""
    an = token(client, "an.gv@lms.test")
    resp = client.get("/courses/c1/grades", headers=auth(an))
    assert resp.status_code == 200
    rows = resp.get_json()
    assert len(rows) >= 1
    for row in rows:
        assert "studentId" in row
        assert "score" in row
        assert "version" in row
        assert isinstance(row["version"], int)


def test_put_grade_missing_version_returns_400(client):
    """PUT điểm thiếu version trả về 400 VALIDATION_ERROR."""
    an = token(client, "an.gv@lms.test")
    # Body chỉ có score, thiếu version
    r = client.put(
        "/courses/c1/grades/u4",
        headers=auth(an),
        json={"score": 8.5},
    )
    assert r.status_code == 400
    assert r.get_json() == {"error": "VALIDATION_ERROR"}

    # Body rỗng
    r_empty = client.put(
        "/courses/c1/grades/u4",
        headers=auth(an),
        json={},
    )
    assert r_empty.status_code == 400
    assert r_empty.get_json() == {"error": "VALIDATION_ERROR"}


def test_optimistic_locking_validation(client):
    """Kiểm tra validation trường version khi sửa điểm."""
    an = token(client, "an.gv@lms.test")
    headers = auth(an)

    # version là string, boolean, <= 0 hoặc trường thừa
    for bad_version in ("1", True, False, 0, -1):
        r = client.put(
            "/courses/c1/grades/u4",
            headers=headers,
            json={"score": 8, "version": bad_version},
        )
        assert r.status_code == 400
        assert r.get_json() == {"error": "VALIDATION_ERROR"}

    # Trường lạ ngoài score và version
    r = client.put(
        "/courses/c1/grades/u4",
        headers=headers,
        json={"score": 8, "version": 1, "extra": "invalid"},
    )
    assert r.status_code == 400
    assert r.get_json() == {"error": "VALIDATION_ERROR"}


def test_update_nonexistent_enrollment_returns_404(client):
    """Nếu sinh viên không tồn tại trong khoá học, trả về 404 NOT_FOUND chứ không phải 409."""
    an = token(client, "an.gv@lms.test")
    r = client.put(
        "/courses/c1/grades/u6",
        headers=auth(an),
        json={"score": 8, "version": 1},
    )
    assert r.status_code == 404
    assert r.get_json() == {"error": "NOT_FOUND"}


def test_store_set_score_requires_version(app):
    """set_score bắt buộc phải truyền version (int), không có giá trị mặc định."""
    import inspect
    from app.errors import Conflict

    store = app.extensions["store"]
    sig = inspect.signature(store.set_score)
    version_param = sig.parameters["version"]
    assert version_param.default is inspect.Parameter.empty, "version must be a required parameter"

    # Gọi không truyền version gây TypeError
    with pytest.raises(TypeError):
        store.set_score("c1", "u4", 9.0)

    # Đọc version qua get_enrollment trước
    enrollment = store.get_enrollment("c1", "u4")
    curr_version = enrollment["version"]

    # Cập nhật thành công với version đúng
    updated = store.set_score("c1", "u4", 8.8, curr_version)
    assert updated["score"] == 8.8
    assert updated["version"] == curr_version + 1

    # Thử cập nhật với version cũ -> Conflict
    with pytest.raises(Conflict):
        store.set_score("c1", "u4", 9.0, curr_version)
