"""Hồi quy V02: UPLOAD_DIR tương đối (cấu hình mặc định) phải ghi và đọc cùng một chỗ.

Trước khi sửa, save_upload() ghi tệp vào <cwd>/uploads còn send_file() của Flask
tìm ở <app.root_path>/uploads, nên tải tài liệu/bài nộp trả 500 và ảnh đại diện
trả 404. Các test cũ luôn truyền UPLOAD_DIR tuyệt đối nên không phát hiện lỗi.
"""

import io

import pytest

from app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Cấu hình mặc định: UPLOAD_DIR tương đối so với thư mục làm việc.
    monkeypatch.chdir(tmp_path)
    app = create_app({
        "JWT_SECRET": "x" * 32,
        "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
    })
    return app.test_client(), app


def token(client, email, password="Lms@2026"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json["accessToken"]


def auth(token_value):
    return {"Authorization": f"Bearer {token_value}"}


def test_relative_upload_dir_is_normalised_to_absolute(client, tmp_path):
    _client, app = client
    upload_dir = app.config["UPLOAD_DIR"]
    assert upload_dir == str((tmp_path / "uploads").resolve())


def test_material_upload_then_download_with_default_config(client, tmp_path):
    client, _app = client
    an = token(client, "an.gv@lms.test")
    chi = token(client, "chi.sv@lms.test")

    payload = b"%PDF-1.4 fake content"
    made = client.post(
        "/courses/c1/materials",
        headers=auth(an),
        data={"file": (io.BytesIO(payload), "slide01.pdf")},
        content_type="multipart/form-data",
    )
    assert made.status_code == 201
    mid = made.json["id"]

    fetched = client.get(f"/materials/{mid}/download", headers=auth(chi))
    assert fetched.status_code == 200
    assert fetched.data == payload
    # Tệp nằm đúng trong thư mục uploads tính từ cwd lúc khởi tạo app.
    assert list((tmp_path / "uploads" / "materials").iterdir())


def test_avatar_upload_then_fetch_with_default_config(client, tmp_path):
    client, _app = client
    chi = token(client, "chi.sv@lms.test")

    uploaded = client.post(
        "/me/avatar",
        headers=auth(chi),
        data={"avatar": (io.BytesIO(b"\x89PNG fake"), "photo.png")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    url = uploaded.json["avatarUrl"]

    fetched = client.get(url)
    assert fetched.status_code == 200
    assert fetched.data == b"\x89PNG fake"
    assert list((tmp_path / "uploads" / "avatars").iterdir())


def test_submission_upload_then_download_with_default_config(client, tmp_path):
    client, _app = client
    an = token(client, "an.gv@lms.test")
    chi = token(client, "chi.sv@lms.test")

    asg = client.post(
        "/courses/c1/assignments",
        headers=auth(an),
        json={
            "title": "Bài tập 1",
            "description": "Nộp báo cáo",
            "dueAt": "2030-01-01T00:00:00+07:00",
        },
    )
    assert asg.status_code == 201
    aid = asg.json["id"]

    payload = b"bai nop cua chi"
    submitted = client.post(
        f"/courses/c1/assignments/{aid}/submissions",
        headers=auth(chi),
        data={"file": (io.BytesIO(payload), "bai-nop.pdf")},
        content_type="multipart/form-data",
    )
    assert submitted.status_code == 201
    sid = submitted.json["id"]

    fetched = client.get(f"/assignments/submissions/{sid}/download", headers=auth(chi))
    assert fetched.status_code == 200
    assert fetched.data == payload
    assert list((tmp_path / "uploads" / "submissions").iterdir())
