import pytest

from db_seed import seed_db


@pytest.fixture(autouse=True)
def _fresh_db():
    """Re-seed the shared Postgres DB between tests."""
    seed_db()
    yield
