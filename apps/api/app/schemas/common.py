from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    status: str
    environment: str
    version: str
    #: Server time. The browser clock is never trusted for "last updated" displays.
    server_time: datetime


class ReadinessResponse(BaseModel):
    status: str
    database: str
    redis: str
    plans_seeded: bool


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    is_admin: bool
    created_at: datetime


class PlanFeatureOut(BaseModel):
    feature_key: str
    value_type: str
    value: bool | int | str
    description: str | None = None


class PlanOut(BaseModel):
    code: str
    name: str
    description: str | None
    price_cents_monthly: int
    currency: str
    sort_order: int
    features: list[PlanFeatureOut]


class EntitlementsOut(BaseModel):
    plan_code: str
    plan_name: str
    subscription_status: str | None
    features: dict[str, bool | int | str]


class MeResponse(BaseModel):
    user: UserOut
    entitlements: EntitlementsOut


class TickerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    name: str
    exchange: str | None
    sector: str | None
    currency: str
    is_big7: bool
