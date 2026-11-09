"""Public plan catalogue. The pricing page renders from this, so pricing changes
are a DB update, not a deploy."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.auth.deps import DbSession
from app.models.plan import Plan
from app.models.ticker import Ticker
from app.schemas.common import PlanFeatureOut, PlanOut, TickerOut
from app.services.entitlements import _coerce

router = APIRouter(tags=["catalogue"])


@router.get("/plans", response_model=list[PlanOut])
def list_plans(db: DbSession) -> list[PlanOut]:
    plans = db.scalars(
        select(Plan)
        .options(selectinload(Plan.features))
        .where(Plan.is_active.is_(True))
        .order_by(Plan.sort_order)
    ).all()

    return [
        PlanOut(
            code=p.code,
            name=p.name,
            description=p.description,
            price_cents_monthly=p.price_cents_monthly,
            currency=p.currency,
            sort_order=p.sort_order,
            features=[
                PlanFeatureOut(
                    feature_key=f.feature_key,
                    value_type=f.value_type.value,
                    value=_coerce(f.value, f.value_type),
                    description=f.description,
                )
                for f in sorted(p.features, key=lambda f: f.feature_key)
            ],
        )
        for p in plans
    ]


@router.get("/tickers/big7", response_model=list[TickerOut])
def big7(db: DbSession) -> list[Ticker]:
    """The free homepage universe. Phase 2 hangs quotes and signals off these."""
    return list(
        db.scalars(
            select(Ticker)
            .where(Ticker.is_big7.is_(True), Ticker.is_active.is_(True))
            .order_by(Ticker.big7_order)
        ).all()
    )
