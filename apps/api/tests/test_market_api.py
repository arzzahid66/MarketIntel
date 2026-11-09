"""The dashboard, refresh and stream endpoints - and the Phase 2 exit criteria:

* a cold cache never blocks a page render
* a provider outage degrades to last-known values with a visible stale state
* outside trading hours the dashboard shows the last close, not a stale "live" number
* the refresh button cannot be used to hammer the provider
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import datetime, timedelta

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.routes import market as market_routes
from app.api.routes.market import get_provider, market_event_stream
from app.core.clock import fixed_clock, get_clock
from app.core.redis import get_redis
from app.main import app
from app.models.market import PriceBar
from app.services import market_data as md
from tests.conftest import auth_headers
from tests.market_helpers import (
    FRIDAY,
    MONDAY_NOON_ET,
    SATURDAY_NOON_ET,
    SpyProvider,
    populate,
)


def use(now: datetime, provider: SpyProvider | None = None) -> SpyProvider:
    spy = provider or SpyProvider(now)
    app.dependency_overrides[get_clock] = lambda: fixed_clock(now)
    app.dependency_overrides[get_provider] = lambda: spy
    return spy


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------


def test_live_market_serves_live_prices_with_signals(client: TestClient, db: Session) -> None:
    populate(db, MONDAY_NOON_ET)
    spy = use(MONDAY_NOON_ET)

    body = client.get("/market/dashboard").json()

    assert body["data_status"] == "live"
    assert body["market"]["is_open"] is True
    assert body["is_simulated"] is True
    assert body["last_updated_at"] == MONDAY_NOON_ET.isoformat().replace("+00:00", "Z")
    assert body["server_time"].startswith("2026-09-14T16:00:00")
    assert [r["symbol"] for r in body["rows"]] == [
        "AAPL",
        "MSFT",
        "GOOGL",
        "AMZN",
        "NVDA",
        "META",
        "TSLA",
    ]
    for row in body["rows"]:
        assert row["price_basis"] == "live"
        assert row["price"] > 0 and not row["is_stale"]
        assert len(row["sparkline"]) == 7
        assert row["signal"] is not None
    assert body["revalidating"] is False
    assert spy.calls == [], "fresh data must not trigger a provider call"


def test_signal_breakdown_is_in_formula_order(client: TestClient, db: Session) -> None:
    populate(db, MONDAY_NOON_ET)
    use(MONDAY_NOON_ET)
    signal = client.get("/market/dashboard").json()["rows"][0]["signal"]
    assert [c["key"] for c in signal["components"]] == [
        "price_vs_50dma_z",
        "rsi14_normalized",
        "return_5d_z",
        "volume_vs_20d_avg_z",
        "news_sentiment_7d",
    ]
    assert signal["components"][-1]["available"] is False


def test_cold_redis_is_served_from_postgres_without_calling_the_provider(
    client: TestClient, db: Session
) -> None:
    populate(db, MONDAY_NOON_ET)
    redis_client = get_redis()
    assert redis_client is not None
    redis_client.flushdb()
    spy = use(MONDAY_NOON_ET)

    started = time.perf_counter()
    body = client.get("/market/dashboard").json()
    elapsed = time.perf_counter() - started

    assert body["data_status"] == "live"
    assert all(r["price"] is not None for r in body["rows"])
    assert spy.calls == []
    assert redis_client.exists("quote:AAPL"), "the miss must warm the cache"
    assert elapsed < 1.5, f"cold-cache dashboard took {elapsed:.2f}s"


def test_empty_system_renders_immediately_then_fills_in_the_background(
    client: TestClient, db: Session
) -> None:
    """Stale-while-revalidate from nothing: the first response has no prices but
    returns at once; the background fetch it starts fills the second."""
    spy = use(MONDAY_NOON_ET)

    first = client.get("/market/dashboard").json()
    assert first["data_status"] == "unavailable"
    assert all(r["price"] is None for r in first["rows"])
    assert first["revalidating"] is True
    assert spy.quote_calls() == 7  # ran after the response, in the background

    second = client.get("/market/dashboard").json()
    assert all(r["price_basis"] == "live" for r in second["rows"])


def test_real_quotes_on_simulated_history_are_still_labelled_simulated(
    client: TestClient, db: Session
) -> None:
    """Configuring a real key does not make yesterday's simulated bars real.

    This is the state right after a provider key is added: live quotes arrive
    from Finnhub while the bars - and so the signal computed from them - are
    still the simulator's. The viewer has to be told, or a fabricated signal
    sits next to a real price with nothing to distinguish it.
    """
    populate(db, MONDAY_NOON_ET)

    class RealProvider(SpyProvider):
        name = "finnhub"
        is_simulated = False

        def get_quote(self, symbol: str):
            quote = super().get_quote(symbol)
            return replace(quote, source=self.name)

    spy = use(MONDAY_NOON_ET, RealProvider(MONDAY_NOON_ET))
    md.ingest_quotes(db, spy, md.big7_tickers(db), MONDAY_NOON_ET, get_redis())

    body = client.get("/market/dashboard").json()

    assert body["provider"] == "finnhub"
    assert all(r["source"] == "finnhub" for r in body["rows"])
    assert all(r["signal"]["source"] == "simulated" for r in body["rows"])
    assert body["is_simulated"] is True


def test_provider_outage_degrades_to_last_known_values(client: TestClient, db: Session) -> None:
    ten_minutes_ago = MONDAY_NOON_ET - timedelta(minutes=10)
    populate(db, MONDAY_NOON_ET, quotes_at=ten_minutes_ago)
    use(MONDAY_NOON_ET, SpyProvider(MONDAY_NOON_ET, fail=True))

    response = client.get("/market/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["data_status"] == "stale"
    assert all(r["is_stale"] and r["price"] is not None for r in body["rows"])
    assert body["last_updated_at"].startswith("2026-09-14T15:50:00")

    # And it stays usable after the failed revalidation.
    again = client.get("/market/dashboard")
    assert again.status_code == 200
    assert again.json()["data_status"] == "stale"


def test_closed_market_shows_the_last_close_not_a_live_number(
    client: TestClient, db: Session
) -> None:
    populate(db, SATURDAY_NOON_ET)
    spy = use(SATURDAY_NOON_ET)

    body = client.get("/market/dashboard").json()
    assert body["data_status"] == "closed"
    assert body["market"]["is_open"] is False
    assert "Weekend" in body["market"]["reason"]

    friday_close = {
        bar.ticker.symbol: bar.close
        for bar in db.query(PriceBar).filter(PriceBar.session_date == FRIDAY).all()
    }
    for row in body["rows"]:
        assert row["price_basis"] == "close"
        assert row["as_of_session"] == FRIDAY.isoformat()
        assert row["price"] == pytest.approx(friday_close[row["symbol"]])
        assert row["provider_time"] is None
    assert spy.calls == []


def test_refresh_interval_follows_the_viewers_plan(
    client: TestClient, db: Session, plus_user: dict, pro_user: dict
) -> None:
    populate(db, MONDAY_NOON_ET)
    use(MONDAY_NOON_ET)

    def interval(headers: dict[str, str]) -> int:
        return client.get("/market/dashboard", headers=headers).json()["refresh_interval_seconds"]

    assert interval({}) == 300
    assert interval(auth_headers(plus_user)) == 60
    assert interval(auth_headers(pro_user)) == 15


# --------------------------------------------------------------------------
# Refresh button
# --------------------------------------------------------------------------


def test_refresh_is_throttled_per_client(client: TestClient, db: Session) -> None:
    populate(db, MONDAY_NOON_ET)
    use(MONDAY_NOON_ET)

    assert client.post("/market/refresh").status_code == 200
    second = client.post("/market/refresh")
    assert second.status_code == 429
    assert second.headers["Retry-After"] == str(market_routes.REFRESH_CLIENT_COOLDOWN_SECONDS)
    assert second.json()["detail"]["error"] == "refresh_throttled"


def test_refresh_cooldown_is_per_browser_not_shared_by_everyone_behind_the_web_server(
    client: TestClient, db: Session
) -> None:
    """All traffic arrives via the Next.js server; X-Forwarded-For tells visitors apart."""
    populate(db, MONDAY_NOON_ET)
    use(MONDAY_NOON_ET)
    alice = {"X-Forwarded-For": "203.0.113.10"}
    bob = {"X-Forwarded-For": "198.51.100.7, 10.0.0.2"}
    assert client.post("/market/refresh", headers=alice).status_code == 200
    assert client.post("/market/refresh", headers=bob).status_code == 200
    assert client.post("/market/refresh", headers=alice).status_code == 429


def test_refresh_does_not_refetch_data_that_is_already_fresh(
    client: TestClient, db: Session
) -> None:
    populate(db, MONDAY_NOON_ET)
    spy = use(MONDAY_NOON_ET)
    body = client.post("/market/refresh").json()
    assert body["revalidating"] is False
    assert spy.calls == []


def test_refresh_fetches_once_however_many_people_press_it(
    client: TestClient, db: Session, free_user: dict, plus_user: dict
) -> None:
    ten_minutes_ago = MONDAY_NOON_ET - timedelta(minutes=10)
    populate(db, MONDAY_NOON_ET, quotes_at=ten_minutes_ago)
    # A failing provider keeps the data stale, so the second press still *wants*
    # to fetch - only the shared lock can stop it.
    spy = use(MONDAY_NOON_ET, SpyProvider(MONDAY_NOON_ET, fail=True))

    first = client.post("/market/refresh", headers=auth_headers(free_user)).json()
    assert first["revalidating"] is True
    assert spy.quote_calls() == 7

    second = client.post("/market/refresh", headers=auth_headers(plus_user)).json()
    assert second["data_status"] == "stale"
    assert second["revalidating"] is False
    assert spy.quote_calls() == 7


def test_refresh_on_a_closed_market_never_calls_the_provider(
    client: TestClient, db: Session
) -> None:
    populate(db, SATURDAY_NOON_ET)
    spy = use(SATURDAY_NOON_ET)
    assert client.post("/market/refresh").json()["revalidating"] is False
    assert spy.calls == []


# --------------------------------------------------------------------------
# Server-sent events
# --------------------------------------------------------------------------


class _Connected:
    def __init__(self, disconnect_after: int | None = None) -> None:
        self.checks = 0
        self.disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self.checks += 1
        return self.disconnect_after is not None and self.checks > self.disconnect_after


def _events(chunks: list[str]) -> list[tuple[str, dict]]:
    events = []
    for chunk in chunks:
        if chunk.startswith("event:"):
            name_line, data_line = chunk.strip().split("\n", 1)
            events.append((name_line.split(": ", 1)[1], json.loads(data_line.split(": ", 1)[1])))
    return events


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_stream_opens_with_a_full_snapshot(db: Session) -> None:
    populate(db, MONDAY_NOON_ET)
    chunks = [
        chunk
        async for chunk in market_event_stream(
            _Connected(),
            None,
            fixed_clock(MONDAY_NOON_ET),
            SpyProvider(MONDAY_NOON_ET),
            max_events=1,
        )
    ]
    assert chunks[0] == "retry: 5000\n\n"
    [(name, payload)] = _events(chunks)
    assert name == "snapshot"
    assert payload["data_status"] == "live"
    assert len(payload["rows"]) == 7


@pytest.mark.anyio
async def test_stream_pushes_again_when_the_worker_publishes(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    populate(db, MONDAY_NOON_ET)
    original = market_routes._snapshot
    # Collapse the plan interval to zero so the test does not wait five minutes.
    monkeypatch.setattr(market_routes, "_snapshot", lambda *a: (original(*a)[0], 0))

    async def publish_soon() -> None:
        await anyio.sleep(0.3)
        md.publish_update(get_redis(), "quotes", MONDAY_NOON_ET)

    chunks: list[str] = []
    async with anyio.create_task_group() as group:
        group.start_soon(publish_soon)
        with anyio.fail_after(10):
            async for chunk in market_event_stream(
                _Connected(),
                None,
                fixed_clock(MONDAY_NOON_ET),
                SpyProvider(MONDAY_NOON_ET),
                poll_seconds=0.1,
                max_events=2,
            ):
                chunks.append(chunk)

    assert [name for name, _ in _events(chunks)] == ["snapshot", "snapshot"]


@pytest.mark.anyio
async def test_stream_holds_updates_until_the_plan_interval(db: Session) -> None:
    """A free viewer is not pushed a new snapshot every time the worker publishes."""
    populate(db, MONDAY_NOON_ET)
    md.publish_update(get_redis(), "quotes", MONDAY_NOON_ET)

    chunks = []
    with anyio.fail_after(10):
        async for chunk in market_event_stream(
            _Connected(disconnect_after=5),
            None,
            fixed_clock(MONDAY_NOON_ET),
            SpyProvider(MONDAY_NOON_ET),
            poll_seconds=0.05,
            heartbeat_seconds=0.1,
        ):
            chunks.append(chunk)

    assert len(_events(chunks)) == 1  # only the opening snapshot
    assert ": keepalive\n\n" in chunks


@pytest.mark.anyio
async def test_stream_ends_when_the_client_leaves(db: Session) -> None:
    populate(db, MONDAY_NOON_ET)
    chunks = []
    with anyio.fail_after(10):
        async for chunk in market_event_stream(
            _Connected(disconnect_after=0),
            None,
            fixed_clock(MONDAY_NOON_ET),
            SpyProvider(MONDAY_NOON_ET),
            poll_seconds=0.05,
        ):
            chunks.append(chunk)
    assert len(_events(chunks)) == 1
