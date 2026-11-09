"""Exponential backoff with full jitter, and its DB pool integration."""

import pytest
import psycopg2
from psycopg2 import pool as pg_pool

from app import db
from app.retry import RetryPolicy, retry, retry_call


def test_delay_grows_exponentially_and_is_capped():
    policy = RetryPolicy(attempts=6, base_delay=0.25, max_delay=1.0, jitter=False)

    assert [policy.delay_for(n) for n in range(1, 6)] == [0.25, 0.5, 1.0, 1.0, 1.0]


def test_full_jitter_is_bounded_by_the_exponential_cap():
    policy = RetryPolicy(base_delay=0.5, max_delay=2.0)

    # retry 3 -> cap = min(2.0, 0.5 * 2**2) = 2.0
    assert policy.delay_for(3, rand=lambda: 0.0) == 0.0
    assert policy.delay_for(3, rand=lambda: 0.5) == pytest.approx(1.0)
    assert policy.delay_for(3, rand=lambda: 1.0) == pytest.approx(2.0)
    assert policy.delay_for(4, rand=lambda: 1.0) == pytest.approx(2.0)


def test_jitter_spreads_delays_for_the_same_retry():
    policy = RetryPolicy(base_delay=1.0, max_delay=10.0)

    delays = {policy.delay_for(2, rand=lambda: value) for value in (0.1, 0.4, 0.9)}

    assert len(delays) == 3
    assert all(0 <= delay <= 2.0 for delay in delays)


def test_retry_call_returns_first_success_and_sleeps_between_attempts():
    calls = []
    sleeps = []
    events = []

    def flaky():
        calls.append(len(calls) + 1)
        if len(calls) < 3:
            raise ConnectionError(f"transient {len(calls)}")
        return "ok"

    result = retry_call(
        flaky,
        policy=RetryPolicy(attempts=3, base_delay=0.1, max_delay=1.0, jitter=True),
        retry_on=ConnectionError,
        sleep=sleeps.append,
        rand=lambda: 1.0,
        on_retry=lambda exc, attempt, delay: events.append((attempt, delay)),
    )

    assert result == "ok"
    assert calls == [1, 2, 3]
    assert sleeps == pytest.approx([0.1, 0.2])
    assert events == [(1, 0.1), (2, 0.2)]


def test_non_retryable_exception_propagates_immediately():
    calls = []

    def broken():
        calls.append(1)
        raise ValueError("do not retry me")

    with pytest.raises(ValueError, match="do not retry me"):
        retry_call(
            broken,
            policy=RetryPolicy(attempts=5, base_delay=0, max_delay=0),
            retry_on=ConnectionError,
            sleep=lambda _: pytest.fail("must not sleep for a non-retryable error"),
        )

    assert calls == [1]


def test_exhausted_attempts_reraise_the_last_error():
    calls = []
    sleeps = []

    def always_fails():
        calls.append(len(calls) + 1)
        raise ConnectionError(f"failure {len(calls)}")

    with pytest.raises(ConnectionError, match="failure 3"):
        retry_call(
            always_fails,
            policy=RetryPolicy(attempts=3, base_delay=0, max_delay=0),
            retry_on=ConnectionError,
            sleep=sleeps.append,
        )

    assert calls == [1, 2, 3]
    assert sleeps == [0.0, 0.0]


def test_attempts_one_means_no_retry():
    calls = []

    def fails():
        calls.append(1)
        raise ConnectionError("once")

    with pytest.raises(ConnectionError):
        retry_call(
            fails,
            policy=RetryPolicy(attempts=1, base_delay=1, max_delay=1),
            retry_on=ConnectionError,
            sleep=lambda _: pytest.fail("attempts=1 must not sleep"),
        )

    assert calls == [1]


def test_retry_on_accepts_a_predicate():
    calls = []

    class Transient(Exception):
        pass

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise Transient("temporary")
        return 7

    result = retry_call(
        flaky,
        policy=RetryPolicy(attempts=2, base_delay=0, max_delay=0),
        retry_on=lambda exc: isinstance(exc, Transient),
        sleep=lambda _: None,
    )

    assert result == 7
    assert calls == [1, 1]


def test_retry_decorator_preserves_arguments_and_name():
    calls = []

    @retry(
        policy=RetryPolicy(attempts=2, base_delay=0, max_delay=0),
        retry_on=ConnectionError,
        sleep=lambda _: None,
    )
    def double(value):
        calls.append(value)
        if len(calls) == 1:
            raise ConnectionError("first")
        return value * 2

    assert double(21) == 42
    assert calls == [21, 21]
    assert double.__name__ == "double"


def test_policy_rejects_invalid_values():
    with pytest.raises(ValueError):
        RetryPolicy(attempts=0)
    with pytest.raises(ValueError):
        RetryPolicy(base_delay=-1)
    with pytest.raises(ValueError):
        RetryPolicy(base_delay=1, max_delay=0.5)
    with pytest.raises(ValueError):
        RetryPolicy().delay_for(0)


class FakeConn:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakePool:
    def __init__(self, conn, failures=0):
        self.conn = conn
        self.failures = failures
        self.checkouts = 0
        self.returned = None

    def getconn(self):
        self.checkouts += 1
        if self.checkouts <= self.failures:
            raise pg_pool.PoolError("connection pool exhausted")
        return self.conn

    def putconn(self, conn):
        self.returned = conn


def test_get_conn_retries_pool_checkout_then_commits(monkeypatch):
    conn = FakeConn()
    pool = FakePool(conn, failures=2)
    monkeypatch.setattr(db, "_pool", pool)
    monkeypatch.setattr(
        db, "_retry_policy", RetryPolicy(attempts=3, base_delay=0, max_delay=0)
    )

    with db.get_conn() as checked_out:
        assert checked_out is conn

    assert pool.checkouts == 3
    assert conn.committed is True
    assert pool.returned is conn


def test_get_conn_rolls_back_body_errors_without_retrying(monkeypatch):
    conn = FakeConn()
    pool = FakePool(conn)
    monkeypatch.setattr(db, "_pool", pool)
    monkeypatch.setattr(
        db, "_retry_policy", RetryPolicy(attempts=5, base_delay=0, max_delay=0)
    )

    with pytest.raises(ValueError, match="bad query"):
        with db.get_conn():
            raise ValueError("bad query")

    assert pool.checkouts == 1
    assert conn.rolled_back is True
    assert conn.committed is False
    assert pool.returned is conn


def test_init_pool_retries_transient_connect_errors(monkeypatch):
    attempts = []

    class FakeConnectionPool:
        def closeall(self):
            pass

    def flaky_create(env, minconn, maxconn):
        attempts.append(1)
        if len(attempts) < 3:
            raise psycopg2.OperationalError("database is starting")
        return FakeConnectionPool()

    monkeypatch.setattr(db, "_pool", None)
    monkeypatch.setattr(db, "_retry_policy", RetryPolicy())
    monkeypatch.setattr(db, "_create_pool", flaky_create)

    db.init_pool(
        {
            "DB_RETRY_ATTEMPTS": "3",
            "DB_RETRY_BASE_DELAY_MS": "0",
            "DB_RETRY_MAX_DELAY_MS": "0",
        }
    )

    assert len(attempts) == 3
    assert isinstance(db._pool, FakeConnectionPool)
    assert db._retry_policy.attempts == 3


def test_init_pool_rejects_invalid_retry_configuration(monkeypatch):
    monkeypatch.setattr(db, "_pool", None)

    with pytest.raises(RuntimeError, match="DB_RETRY_ATTEMPTS"):
        db.init_pool({"DB_RETRY_ATTEMPTS": "0"})

    with pytest.raises(RuntimeError, match="DB_RETRY_MAX_DELAY_MS"):
        db.init_pool(
            {
                "DB_RETRY_ATTEMPTS": "2",
                "DB_RETRY_BASE_DELAY_MS": "500",
                "DB_RETRY_MAX_DELAY_MS": "100",
            }
        )
