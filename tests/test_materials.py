import io

import pytest

from app import create_app


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


def upload(client, headers, name="slide01.pdf", cid="c1"):
    return client.post(
        f"/courses/{cid}/materials",
        headers=headers,
        data={"file": (io.BytesIO(b"%PDF-1.4 fake"), name)},
        content_type="multipart/form-data",
    )


def test_upload_list_download_delete_flow(client):
    an = token(client, "an.gv@lms.test")
    chi = token(client, "chi.sv@lms.test")

    made = upload(client, auth(an))
    assert made.status_code == 201
    mid = made.json["id"]

    rows = client.get("/courses/c1/materials", headers=auth(chi)).json
    assert [r["id"] for r in rows] == [mid]
    assert rows[0]["originalName"] == "slide01.pdf"

    fetched = client.get(f"/materials/{mid}/download", headers=auth(chi))
    assert fetched.status_code == 200

    deleted = client.delete(f"/materials/{mid}", headers=auth(an))
    assert deleted.status_code == 200
    assert client.get("/courses/c1/materials", headers=auth(chi)).json == []


def test_access_control(client):
    an = token(client, "an.gv@lms.test")
    chi = token(client, "chi.sv@lms.test")
    binh = token(client, "binh.gv@lms.test")
    em = token(client, "em.sv@lms.test")

    made = upload(client, auth(an))
    mid = made.json["id"]

    # Student cannot upload, other instructor cannot list/delete c1.
    assert upload(client, auth(chi)).status_code == 403
    assert client.get("/courses/c1/materials", headers=auth(binh)).status_code == 403
    assert client.delete(f"/materials/{mid}", headers=auth(binh)).status_code == 403
    # Student outside the course cannot download.
    assert client.get(f"/materials/{mid}/download", headers=auth(em)).status_code == 403


def test_bad_extension_rejected(client):
    an = token(client, "an.gv@lms.test")
    bad = upload(client, auth(an), name="payload.sh")
    assert bad.status_code == 400
