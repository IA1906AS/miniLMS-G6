"""Send five overlapping grade exports and print one result per slot.

Run from the repository root: uv run --no-sync python scripts/check_bulkhead.py
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, routes  # noqa: E402


def main():
    with TemporaryDirectory() as directory:
        app = create_app({
            "JWT_SECRET": "bulkhead-script-local-only-secret-32-chars",
            "AUDIT_LOG_PATH": str(Path(directory) / "audit.log"),
        })
        client = app.test_client()
        login = client.post("/auth/login", json={
            "email": "chi.sv@lms.test", "password": "Lms@2026",
        })
        if login.status_code != 200:
            raise RuntimeError("Không đăng nhập được bằng tài khoản kiểm thử")
        headers = {"Authorization": f"Bearer {login.json['accessToken']}"}

        original_render = routes.render_grade_csv
        two_active = Event()
        release = Event()
        lock = Lock()
        active = 0

        def slow_render(rows):
            nonlocal active
            with lock:
                active += 1
                if active == 2:
                    two_active.set()
            try:
                if not release.wait(10):
                    raise TimeoutError("Hai request đầu không được nhả")
                return original_render(rows)
            finally:
                with lock:
                    active -= 1

        def export():
            return app.test_client().get("/courses/c1/grades/export", headers=headers)

        results = [False] * 5

        def response_or_none(future):
            try:
                return future.result(timeout=10)
            except Exception:
                return None

        routes.render_grade_csv = slow_render
        try:
            with ThreadPoolExecutor(max_workers=5) as pool:
                first = [pool.submit(export) for _ in range(2)]
                try:
                    ready = two_active.wait(10)
                    last = [pool.submit(export) for _ in range(3)]
                    for index, future in enumerate(last, start=2):
                        response = response_or_none(future)
                        results[index] = (ready and response is not None and
                                          response.status_code == 503 and
                                          response.json == {"error": "EXPORT_BUSY"})
                finally:
                    release.set()
                for index, future in enumerate(first):
                    response = response_or_none(future)
                    results[index] = (ready and response is not None and
                                      response.status_code == 200)
        finally:
            routes.render_grade_csv = original_render
            release.set()

        for index, passed in enumerate(results, start=1):
            print(f"[+] Slot {index}: {'Pass' if passed else 'Failed'}")
        if not all(results):
            sys.exit(1)


if __name__ == "__main__":
    main()
