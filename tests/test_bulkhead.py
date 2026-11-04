"""Bulkhead behavior at the grade-export HTTP boundary."""

import csv
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

import pytest

from app import create_app
from app.auth import create_token
from app.guards import ExportBulkhead, ExportBusy


@pytest.fixture
def app(tmp_path):
    return create_app({
        "JWT_SECRET": "bulkhead-test-secret-of-at-least-32-characters",
        "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
    })


@pytest.fixture
def headers(app):
    with app.app_context():
        return {"Authorization": f"Bearer {create_token('u2')}"}


def test_bulkhead_rejects_at_capacity_and_releases_after_exception():
    limiter = ExportBulkhead(limit=2)
    with limiter.slot():
        with limiter.slot():
            with pytest.raises(ExportBusy):
                with limiter.slot():
                    pass
        with pytest.raises(RuntimeError):
            with limiter.slot():
                raise RuntimeError("export failed")
    with limiter.slot():
        pass


def test_export_returns_authorized_csv_and_other_routes_still_work(app, headers):
    client = app.test_client()
    response = client.get("/courses/c1/grades/export", headers=headers)
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert response.headers["Content-Disposition"] == 'attachment; filename="grades-c1.csv"'
    assert list(csv.DictReader(io.StringIO(response.get_data(as_text=True)))) == [
        {"studentId": "u4", "score": "7.5"},
        {"studentId": "u5", "score": "8.0"},
    ]
    assert client.get("/courses/c1/grades", headers=headers).status_code == 200
    assert client.post("/auth/login", json={
        "email": "chi.sv@lms.test", "password": "Lms@2026",
    }).status_code == 200


def test_export_preserves_grade_authorization(app, headers):
    client = app.test_client()
    assert client.get("/courses/c1/grades/export").status_code == 401
    assert client.get("/courses/missing/grades/export", headers=headers).status_code == 404
    with app.app_context():
        other_instructor = {"Authorization": f"Bearer {create_token('u3')}"}
        student = {"Authorization": f"Bearer {create_token('u4')}"}
    assert client.get("/courses/c1/grades/export", headers=other_instructor).status_code == 403
    response = client.get("/courses/c1/grades/export", headers=student)
    assert response.status_code == 200
    assert list(csv.DictReader(io.StringIO(response.get_data(as_text=True)))) == [
        {"studentId": "u4", "score": "7.5"},
    ]


def test_five_concurrent_exports_reject_three_without_blocking_grade_view(app, headers, monkeypatch):
    from app import routes

    original = routes.render_grade_csv
    release = Event()
    two_active = Event()
    lock = Lock()
    active = 0
    peak = 0

    def slow_render(rows):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                two_active.set()
        try:
            assert release.wait(10), "export workers did not get released"
            return original(rows)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(routes, "render_grade_csv", slow_render)

    def export():
        return app.test_client().get("/courses/c1/grades/export", headers=headers)

    with ThreadPoolExecutor(max_workers=5) as pool:
        first_two = [pool.submit(export) for _ in range(2)]
        try:
            assert two_active.wait(10), "two exports did not enter the renderer"
            start = Barrier(4)

            def extra_export():
                start.wait(timeout=10)
                return export()

            extras = [pool.submit(extra_export) for _ in range(3)]
            start.wait(timeout=10)
            rejected = [future.result(timeout=10) for future in extras]
            assert [response.status_code for response in rejected] == [503, 503, 503]
            assert all(response.json == {"error": "EXPORT_BUSY"} for response in rejected)
            assert app.test_client().get("/courses/c1/grades", headers=headers).status_code == 200
            assert peak == 2
        finally:
            release.set()
        assert [future.result(timeout=10).status_code for future in first_two] == [200, 200]
    assert export().status_code == 200


def test_failed_export_releases_slot(app, headers, monkeypatch):
    from app import routes

    def fail(_rows):
        raise RuntimeError("report failed")

    monkeypatch.setattr(routes, "render_grade_csv", fail)
    client = app.test_client()
    for _ in range(3):
        assert client.get("/courses/c1/grades/export", headers=headers).status_code == 500
    assert client.get("/courses/c1/grades", headers=headers).status_code == 200
