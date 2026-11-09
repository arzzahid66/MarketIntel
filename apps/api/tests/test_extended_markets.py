"""Extended markets: the heatmap, the calendar, and the plan gate (Phase 5).

The gate here is the interesting part, because it is *not* a 402. The plan
matrix gives Free "Delayed / partial", so `markets.extended_access` is a string
feature and the API builds a smaller payload rather than refusing the request.
These tests hold that line from both directions: Free must get the sector
picture, and Free must not get the per-name detail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.market import get_provider
from app.core.clock import fixed_clock, get_clock
from app.core.redis import get_redis
from app.main import app
from app.models.calendar import EarningsEvent
from app.models.plan import Plan, PlanFeature
from app.models.ticker import Ticker
from app.providers.fake import FakeProvider
from app.services import calendar_ingest
from app.services import features as F
from app.services import market_data as md
from app.services import markets as markets_service
from app.services.sector import Constituent, build_tiles, weighted_change
from app.sources.fake_calendar import FakeEarningsCalendar
from tests.conftest import auth_headers
from tests.market_helpers import SpyProvider

NOW = datetime(2026, 9, 14, 16, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def frozen_clock():
    app.dependency_overrides[get_clock] = lambda: fixed_clock(NOW)
    yield
    app.dependency_overrides.pop(get_clock, None)


def quote_the_universe(db: Session) -> None:
    """Prices and market caps for every active name.

    Caps come from the nightly profile job and the heatmap weights on them, so a
    heatmap test without them would only be exercising the "unknown" path.
    """
    tickers = markets_service.universe_tickers(db)
    md.ingest_quotes(db, FakeProvider(fixed_clock(NOW)), tickers, NOW, get_redis())
    md.refresh_profiles(db, FakeProvider(fixed_clock(NOW)), tickers, NOW)


# ---------------------------------------------------------------------------
# Sector aggregation - pure maths, no I/O
# ---------------------------------------------------------------------------


def test_a_sector_move_is_market_cap_weighted_not_an_average() -> None:
    """An equal-weight mean lets the smallest name swing the tile as hard as
    the largest, which is not what "Technology is down today" means.

    3T down 1% against 1T up 2% is -0.25%, not the +0.5% an average gives.
    """
    change, cap, counted = weighted_change(
        [
            Constituent("BIG", "Big", 3e12, -1.0, 100.0, True),
            Constituent("SMALL", "Small", 1e12, 2.0, 50.0, False),
        ]
    )
    assert change == pytest.approx(-0.25)
    assert cap == pytest.approx(4e12)
    assert counted == 2


def test_an_uncomputable_sector_is_none_rather_than_zero_percent() -> None:
    """Unknown must not render as flat: a grey tile is honest, a green one lies."""
    change, _, counted = weighted_change(
        [
            Constituent("X", "X", None, 5.0, 1.0, False),
            Constituent("Y", "Y", 1e9, None, 1.0, False),
        ]
    )
    assert change is None
    assert counted == 0

    tile = build_tiles({"Technology": [Constituent("X", "X", None, 5.0, 1.0, False)]})[0]
    assert tile.change_percent is None
    assert tile.intensity == 0.0


def test_a_name_without_a_cap_is_listed_but_not_weighted() -> None:
    """Dropping it makes a tile whose constituents do not add up to it;
    weighting it means inventing a market cap."""
    tile = build_tiles(
        {
            "Technology": [
                Constituent("A", "A", 2e12, 1.0, 10.0, True),
                Constituent("B", "B", None, -50.0, 10.0, False),
            ]
        }
    )[0]
    assert tile.count == 2
    assert tile.weighted_count == 1
    assert len(tile.constituents) == 2
    assert tile.change_percent == pytest.approx(1.0), "the capless name must not move the tile"


def test_names_without_a_sector_are_grouped_not_dropped() -> None:
    """An unclassified holding is a data gap to fix; hiding it hides the gap."""
    tiles = build_tiles({None: [Constituent("Q", "Q", 1e9, 0.5, 2.0, False)]})
    assert [tile.sector for tile in tiles] == ["Unclassified"]


def test_tiles_come_back_largest_first() -> None:
    """The treemap lays out big tiles first, so the eye lands on what moves
    the market rather than on whatever sorted alphabetically."""
    tiles = build_tiles(
        {
            "Small": [Constituent("S", "S", 1e9, 0.0, 1.0, False)],
            "Huge": [Constituent("H", "H", 5e12, 0.0, 1.0, False)],
            "Mid": [Constituent("M", "M", 2e11, 0.0, 1.0, False)],
        }
    )
    assert [tile.sector for tile in tiles] == ["Huge", "Mid", "Small"]


# ---------------------------------------------------------------------------
# The plan gate
# ---------------------------------------------------------------------------


def test_free_sees_every_sector_but_no_constituents(
    client: TestClient, db: Session, free_user: dict
) -> None:
    """ "Delayed / partial" in the matrix means less detail, not an empty page."""
    quote_the_universe(db)

    response = client.get("/market/heatmap", headers=auth_headers(free_user))
    assert response.status_code == 200
    body = response.json()

    assert body["access"] == "delayed"
    assert len(body["tiles"]) > 1, "Free must still see the sector picture"
    assert all(tile["constituents"] == [] for tile in body["tiles"])


def test_plus_sees_the_companies_inside_each_sector(
    client: TestClient, db: Session, plus_user: dict
) -> None:
    quote_the_universe(db)

    body = client.get("/market/heatmap", headers=auth_headers(plus_user)).json()
    assert body["access"] == "full"
    assert any(tile["constituents"] for tile in body["tiles"])


def test_paid_detail_is_absent_from_the_payload_not_hidden_in_the_ui(
    client: TestClient, db: Session, free_user: dict
) -> None:
    """A gate enforced by the client is not a gate.

    Serialising the names and letting the page skip them would ship paid data to
    anyone who opens the network tab.
    """
    quote_the_universe(db)
    hidden = list(
        db.scalars(select(Ticker.symbol).where(Ticker.is_big7.is_(False)).limit(10)).all()
    )
    assert hidden, "the seeded universe should contain non-Big-7 names"

    raw = client.get("/market/heatmap", headers=auth_headers(free_user)).text
    for symbol in hidden:
        assert f'"{symbol}"' not in raw, f"{symbol} leaked into a delayed payload"


def test_an_unknown_access_value_fails_closed(
    client: TestClient, db: Session, free_user: dict
) -> None:
    """A garbled plan row must not hand out the paid payload."""
    plan = db.scalars(select(Plan).where(Plan.code == "free")).one()
    feature = db.scalars(
        select(PlanFeature).where(
            PlanFeature.plan_id == plan.id,
            PlanFeature.feature_key == F.EXTENDED_MARKETS_ACCESS,
        )
    ).one()
    feature.value = "platinum-deluxe"
    db.commit()

    quote_the_universe(db)
    body = client.get("/market/heatmap", headers=auth_headers(free_user)).json()
    assert body["access"] == "delayed"
    assert all(tile["constituents"] == [] for tile in body["tiles"])


def test_the_heatmap_never_calls_a_provider(
    client: TestClient, db: Session, plus_user: dict
) -> None:
    """Same rule as the dashboard: a request path reads cache and Postgres only.

    Forty-eight tickers make this matter more than it did at seven - one
    provider call per tile per pageview would exhaust a free-tier minute budget
    on a single visitor.
    """
    quote_the_universe(db)
    spy = SpyProvider(NOW)
    app.dependency_overrides[get_provider] = lambda: spy

    assert client.get("/market/heatmap", headers=auth_headers(plus_user)).status_code == 200
    assert spy.calls == [], f"the heatmap called a provider: {spy.calls}"

    assert client.get("/market/calendar", headers=auth_headers(plus_user)).status_code == 200
    assert spy.calls == [], f"the calendar called a provider: {spy.calls}"


# ---------------------------------------------------------------------------
# The calendar
# ---------------------------------------------------------------------------


def test_the_calendar_window_is_shorter_on_a_delayed_plan(
    client: TestClient, db: Session, free_user: dict, plus_user: dict
) -> None:
    calendar_ingest.ingest_earnings(db, FakeEarningsCalendar(), NOW)

    free = client.get("/market/calendar", headers=auth_headers(free_user)).json()
    plus = client.get("/market/calendar", headers=auth_headers(plus_user)).json()

    assert free["until"] < plus["until"]
    # Both are told where the full window reaches, so the upgrade prompt can be
    # specific rather than vague.
    assert free["full_until"] == plus["until"]


def test_the_calendar_only_lists_companies_we_carry_a_price_for(
    client: TestClient, db: Session, plus_user: dict
) -> None:
    """The provider returns the whole market - 4,600 rows for a month. A
    calendar of companies the dashboard cannot price is noise, not a feature."""
    db.add(
        EarningsEvent(
            symbol="NOTOURS",
            ticker_id=None,
            session_date=(NOW + timedelta(days=3)).date(),
            timing="bmo",
            fiscal_quarter=1,
            fiscal_year=2026,
            eps_estimate=1.0,
            eps_actual=None,
            revenue_estimate=None,
            revenue_actual=None,
            source="test",
            fetched_at=NOW,
        )
    )
    db.commit()
    calendar_ingest.ingest_earnings(db, FakeEarningsCalendar(), NOW)

    body = client.get("/market/calendar", headers=auth_headers(plus_user)).json()
    assert body["events"], "our own universe should appear"
    assert all(event["symbol"] != "NOTOURS" for event in body["events"])


def test_re_ingesting_the_calendar_revises_rather_than_duplicates(db: Session) -> None:
    """The reason to re-fetch a date already held is that the estimate moved or
    the actual landed, so this upserts. DO NOTHING would freeze the first guess."""
    first = calendar_ingest.ingest_earnings(db, FakeEarningsCalendar(), NOW)
    before = len(list(db.scalars(select(EarningsEvent)).all()))
    assert before > 0

    row = db.scalars(select(EarningsEvent).limit(1)).one()
    symbol, session_date = row.symbol, row.session_date
    row.eps_estimate = -99.0
    db.commit()

    second = calendar_ingest.ingest_earnings(db, FakeEarningsCalendar(), NOW)

    assert first.written == second.written
    assert len(list(db.scalars(select(EarningsEvent)).all())) == before

    db.expire_all()
    refreshed = db.scalars(
        select(EarningsEvent).where(
            EarningsEvent.symbol == symbol,
            EarningsEvent.session_date == session_date,
        )
    ).one()
    assert refreshed.eps_estimate != -99.0, "a re-run must overwrite a stale estimate"


def test_the_calendar_stub_produces_both_reported_and_scheduled_rows() -> None:
    """Development data has to contain both shapes, or the one case that is easy
    to get wrong - an actual of None rendering as 0.00 - is never exercised."""
    events = FakeEarningsCalendar().fetch(
        (NOW - timedelta(days=20)).date(), (NOW + timedelta(days=20)).date()
    )
    assert any(event.eps_actual is not None for event in events)
    assert any(event.eps_actual is None for event in events)
