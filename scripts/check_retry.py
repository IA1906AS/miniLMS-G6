"""Verify exponential backoff with full jitter and the DB checkout retry path.

Run from the repository root (no PostgreSQL required):

    python scripts/check_retry.py

The DB part replaces the module-level pool with a fake object, so the script
only exercises retry logic, not a real database connection.
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from psycopg2 import pool as pg_pool  # noqa: E402

from app import db  # noqa: E402
from app.retry import RetryPolicy, retry_call  # noqa: E402


def main():
    deterministic = RetryPolicy(attempts=5, base_delay=0.2, max_delay=1.0, jitter=False)
    delays = [deterministic.delay_for(retry) for retry in range(1, 5)]
    assert delays == [0.2, 0.4, 0.8, 1.0], delays
    print(f"PASS: exponential delays without jitter = {delays}")

    jittered = RetryPolicy(attempts=5, base_delay=0.2, max_delay=1.0)
    rng = random.Random(2026)
    samples = [jittered.delay_for(4, rand=rng.random) for _ in range(200)]
    assert all(0.0 <= delay <= 1.0 for delay in samples), "jitter escaped the cap"
    assert len(set(samples)) > 100, "jitter is not spreading delays"
    print(
        "PASS: full jitter stays in [0, 1.0] with "
        f"{len(set(samples))} distinct values across 200 samples"
    )

    calls = []
    sleeps = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError(f"transient {len(calls)}")
        return "ok"

    result = retry_call(
        flaky,
        policy=RetryPolicy(attempts=3, base_delay=0.1, max_delay=1.0),
        retry_on=ConnectionError,
        sleep=sleeps.append,
        rand=lambda: 1.0,
    )
    assert result == "ok"
    assert len(calls) == 3 and sleeps == [0.1, 0.2], (calls, sleeps)
    print(f"PASS: two transient failures retried with delays {sleeps}")

    calls.clear()

    def always_fails():
        calls.append(1)
        raise ConnectionError("database down")

    try:
        retry_call(
            always_fails,
            policy=RetryPolicy(attempts=3, base_delay=0, max_delay=0),
            retry_on=ConnectionError,
            sleep=lambda _: None,
        )
    except ConnectionError as exc:
        assert str(exc) == "database down"
    else:
        raise AssertionError("expected the last ConnectionError to be re-raised")
    assert len(calls) == 3, calls
    print("PASS: retries exhausted after 3 attempts and re-raised the last error")

    class FakeConn:
        def __init__(self):
            self.committed = False
            self.rolled_back = False

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

    class FlakyPool:
        def __init__(self, conn):
            self.conn = conn
            self.checkouts = 0
            self.returned = None

        def getconn(self):
            self.checkouts += 1
            if self.checkouts < 3:
                raise pg_pool.PoolError("connection pool exhausted")
            return self.conn

        def putconn(self, conn):
            self.returned = conn

    conn = FakeConn()
    pool = FlakyPool(conn)
    original_pool, original_policy = db._pool, db._retry_policy
    try:
        db._pool = pool
        db._retry_policy = RetryPolicy(attempts=3, base_delay=0, max_delay=0)
        with db.get_conn() as checked_out:
            assert checked_out is conn
    finally:
        db._pool = original_pool
        db._retry_policy = original_policy

    assert pool.checkouts == 3, pool.checkouts
    assert conn.committed and not conn.rolled_back
    assert pool.returned is conn
    print("PASS: get_conn retried pool checkout 3x, then committed and returned the connection")

    print("All retry checks passed.")


if __name__ == "__main__":
    main()
