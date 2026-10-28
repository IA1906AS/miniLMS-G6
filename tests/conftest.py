import pytest

from app import auth
from db_seed import seed_db


@pytest.fixture(autouse=True)
def _fresh_state():
    """Re-seed the shared Postgres DB and clear lockout state between tests."""
    seed_db()
    auth._failures().clear()
    yield
