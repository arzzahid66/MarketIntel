"""Test harness.

Tests run against a real Postgres (`mip_test` on the docker-compose instance),
not SQLite. The schema uses native enums, UUID columns and ON DELETE rules that
SQLite would silently not enforce - a test suite that cannot catch those is
worse than no test suite.

The schema is built by running the Alembic migrations, so every test run is also
a migration test.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

# Must be set before anything imports app.core.config.
TEST_DB_NAME = os.environ.get("TEST_DB_NAME", "mip_test")
ADMIN_DB_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL", "postgresql+psycopg://mip:mip@localhost:5433/mip"
)
TEST_DB_URL = ADMIN_DB_URL.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"

os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["ENVIRONMENT"] = "test"
os.environ["AUTH_PROVIDER"] = "local"
os.environ["JWT_SECRET"] = "test-secret-not-used-anywhere-real"
os.environ["SENTRY_DSN"] = ""
# A real Redis, on its own logical database, flushed before every test. The
# token bucket is a Lua script and the SSE stream uses pub/sub; a mock of either
# would test the mock.
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/15")
# Never let a developer's real provider key in .env turn the suite into a stream
# of paid API calls.
os.environ["MARKET_DATA_PROVIDER"] = "fake"
os.environ["FINNHUB_API_KEY"] = ""
os.environ["TWELVEDATA_API_KEY"] = ""
# Same again for the LLM: a suite that silently billed per run would be found
# out on the invoice, not in CI.
os.environ["LLM_PROVIDER"] = "fake"
os.environ["OPENAI_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.redis import get_redis  # noqa: E402
from app.db.seed import seed_all  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.plan import Plan  # noqa: E402
from app.models.subscription import Subscription, SubscriptionStatus  # noqa: E402
from app.models.user import User  # noqa: E402

#: Tables wiped between tests. Reference data (plans, tickers, feed categories)
#: is seeded once, so those tables are deliberately absent.
MUTABLE_TABLES = (
    "chat_flags",
    "chat_messages",
    "ai_messages",
    "feed_item_tickers",
    "feed_items",
    "signal_snapshots",
    "price_bars",
    "latest_quotes",
    "earnings_events",
    "watchlist_items",
    "watchlists",
    "subscriptions",
    "users",
)


def _ensure_test_database() -> None:
    admin_engine = create_engine(ADMIN_DB_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DB_NAME}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    _ensure_test_database()

    from alembic.config import Config

    from alembic import command

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)

    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    with SessionLocal() as db:
        seed_all(db)

    yield

    engine.dispose()


@pytest.fixture(autouse=True)
def clean_state() -> Iterator[None]:
    redis_client = get_redis()
    if redis_client is not None:
        redis_client.flushdb()
    yield
    app.dependency_overrides.clear()
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(MUTABLE_TABLES)} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

VALID_PASSWORD = "correct-horse-battery"


def signup(client: TestClient, email: str, password: str = VALID_PASSWORD) -> dict:
    response = client.post(
        "/auth/signup",
        json={"email": email, "password": password, "display_name": "Test User"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth_headers(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture
def free_user(client: TestClient) -> dict:
    """A signed-up user with no subscription row at all - the default state."""
    return signup(client, "free@example.com")


@pytest.fixture
def plus_user(client: TestClient, db: Session) -> dict:
    tokens = signup(client, "plus@example.com")
    _subscribe(db, "plus@example.com", "plus", SubscriptionStatus.ACTIVE)
    return tokens


@pytest.fixture
def pro_user(client: TestClient, db: Session) -> dict:
    tokens = signup(client, "pro@example.com")
    _subscribe(db, "pro@example.com", "pro", SubscriptionStatus.ACTIVE)
    return tokens


def _subscribe(db: Session, email: str, plan_code: str, status: SubscriptionStatus) -> Subscription:
    from sqlalchemy import select

    user = db.scalars(select(User).where(User.email == email)).one()
    plan = db.scalars(select(Plan).where(Plan.code == plan_code)).one()
    subscription = Subscription(user_id=user.id, plan_id=plan.id, status=status)
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription
