"""Exercise five concurrent grade exports through Flask's real request pipeline.

Run from the repository root on Windows:
    uv run --no-sync --python 3.14 python scripts/check_bulkhead.py

This tests one Flask process; it does not measure a multi-process server.
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event, Lock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, routes  # noqa: E402
from app.auth import create_token  # noqa: E402


def main():
    with TemporaryDirectory() as directory:
        app = create_app({
            "JWT_SECRET": "bulkhead-script-local-only-secret-32-chars",
            "AUDIT_LOG_PATH": str(Path(directory) / "audit.log"),
        })
        with app.app_context():
            headers = {"Authorization": f"Bearer {create_token('u2')}"}

        original_render = routes.render_grade_csv
        entered = Event()
        release = Event()
        lock = Lock()
        active = 0
        peak = 0

        def slow_render(rows):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if active == 2:
                    entered.set()
            try:
                if not release.wait(10):
                    raise AssertionError("Export workers timed out")
                return original_render(rows)
            finally:
                with lock:
                    active -= 1

        def export():
            return app.test_client().get("/courses/c1/grades/export", headers=headers)

        routes.render_grade_csv = slow_render
        try:
            with ThreadPoolExecutor(max_workers=5) as pool:
                admitted = [pool.submit(export) for _ in range(2)]
                try:
                    assert entered.wait(10), "Two exports did not enter the renderer"
                    start = Barrier(4)

                    def extra_export():
                        start.wait(timeout=10)
                        return export()

                    extras = [pool.submit(extra_export) for _ in range(3)]
                    start.wait(timeout=10)
                    rejected = [future.result(timeout=10) for future in extras]
                    assert all(response.status_code == 503 for response in rejected)
                    assert all(response.json == {"error": "EXPORT_BUSY"} for response in rejected)
                    grades = app.test_client().get("/courses/c1/grades", headers=headers)
                    assert grades.status_code == 200
                    assert peak == 2, f"Expected peak 2, got {peak}"
                finally:
                    release.set()
                completed = [future.result(timeout=10) for future in admitted]
                assert all(response.status_code == 200 for response in completed)
        finally:
            routes.render_grade_csv = original_render
            release.set()

        assert export().status_code == 200, "Slot was not released after successful exports"

        def broken_render(_rows):
            raise RuntimeError("simulated export failure")

        routes.render_grade_csv = broken_render
        try:
            assert export().status_code == 500, "Failed export should return 500"
        finally:
            routes.render_grade_csv = original_render
        assert export().status_code == 200, "Slot was not released after a failed export"
        print("PASS: 5 concurrent exports -> 2 x 200, 3 x 503; peak=2")
        print("PASS: grade view=200 during contention; slots released on success and failure")


if __name__ == "__main__":
    main()
