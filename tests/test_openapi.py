import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app({
        "JWT_SECRET": "x" * 32,
        "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
    })
    return app.test_client()


def test_openapi_spec_is_public_and_served(client):
    response = client.get("/api/openapi.yaml")
    assert response.status_code == 200
    assert response.mimetype == "text/yaml"
    body = response.get_data(as_text=True)
    assert body.startswith("openapi:")
    for path in (
        "/auth/login",
        "/me/avatar",
        "/courses/enroll",
        "/materials/{materialId}/download",
        "/topics/{topicId}",
        "/admin/audit",
    ):
        assert path in body
