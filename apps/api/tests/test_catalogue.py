from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.seed import BIG7, PLAN_MATRIX


def test_plans_endpoint_drives_the_pricing_page(client: TestClient) -> None:
    plans = client.get("/plans").json()
    assert [p["code"] for p in plans] == [spec.code for spec in PLAN_MATRIX]
    assert plans[0]["price_cents_monthly"] == 0


def test_plan_feature_values_are_typed_not_strings(client: TestClient) -> None:
    free = next(p for p in client.get("/plans").json() if p["code"] == "free")
    values = {f["feature_key"]: f["value"] for f in free["features"]}
    assert values["chat.can_post"] is False
    assert values["data.refresh_interval_seconds"] == 300
    assert values["markets.extended_access"] == "delayed"


def test_big7_is_seeded_and_ordered(client: TestClient) -> None:
    tickers = client.get("/tickers/big7").json()
    assert len(tickers) == 7
    assert [t["symbol"] for t in tickers] == [row[0] for row in BIG7]
    assert all(t["is_big7"] for t in tickers)


def test_seed_is_idempotent(db) -> None:  # type: ignore[no-untyped-def]
    """Deploys run the seed every time; running it twice must change nothing."""
    from sqlalchemy import func, select

    from app.db.seed import seed_all
    from app.models.plan import PlanFeature
    from app.models.ticker import Ticker

    before = (
        db.scalar(select(func.count()).select_from(PlanFeature)),
        db.scalar(select(func.count()).select_from(Ticker)),
    )
    seed_all(db)
    after = (
        db.scalar(select(func.count()).select_from(PlanFeature)),
        db.scalar(select(func.count()).select_from(Ticker)),
    )
    assert before == after
