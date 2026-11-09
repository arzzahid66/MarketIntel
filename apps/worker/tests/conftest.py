"""Worker test harness: the same real Postgres (`mip_test`) and Redis (db 15) as the API suite."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://mip:mip@localhost:5433/mip_test"
)
os.environ["ENVIRONMENT"] = "test"
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/15")
os.environ["MARKET_DATA_PROVIDER"] = "fake"
os.environ["FINNHUB_API_KEY"] = ""
os.environ["TWELVEDATA_API_KEY"] = ""
# The LLM must be stubbed too, and explicitly rather than by clearing the key:
# `score_news` and `embed_news` are real jobs in this suite, so without this the
# run scores and embeds against the live API and bills for every pass. The API
# suite has always set these; the worker suite did not, and the tell was
# `news_scored model=gpt-4.1-mini` in the test output.
os.environ["LLM_PROVIDER"] = "fake"
os.environ["OPENAI_API_KEY"] = ""
# Same reasoning for the earnings calendar: `auto` plus a key means a real call.
os.environ["NEWS_SOURCE"] = "fake"
os.environ["CALENDAR_SOURCE"] = "fake"

from app.core.redis import get_redis
from app.db.seed import seed_all
from app.db.session import SessionLocal, engine
from sqlalchemy import create_engine, text

MARKET_TABLES = ("signal_snapshots", "price_bars", "latest_quotes", "earnings_events")


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    url = os.environ["DATABASE_URL"]
    admin = create_engine(url.rsplit("/", 1)[0] + "/mip", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        name = url.rsplit("/", 1)[1]
        if not conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
        ).scalar():
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()

    from alembic import command
    from alembic.config import Config

    api_dir = os.path.join(os.path.dirname(__file__), "..", "..", "api")
    cfg = Config(os.path.join(api_dir, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(api_dir, "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    with SessionLocal() as db:
        seed_all(db)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_state() -> Iterator[None]:
    client = get_redis()
    if client is not None:
        client.flushdb()
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(MARKET_TABLES)}"))
    yield
