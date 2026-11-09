from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

PriceBasis = Literal["live", "close", "none"]
DataStatus = Literal["live", "closed", "stale", "unavailable"]


class SignalComponentOut(BaseModel):
    key: str
    label: str
    weight: float
    raw: float | None
    normalized: float
    contribution: float
    available: bool


class SignalOut(BaseModel):
    score: float
    band: str
    computed_at: datetime
    formula_version: int
    components: list[SignalComponentOut]
    notes: list[str]
    intraday: bool
    as_of_session: str | None
    is_stale: bool
    source: str


class MarketRowOut(BaseModel):
    symbol: str
    name: str
    currency: str
    price: float | None
    change: float | None
    change_percent: float | None
    previous_close: float | None
    #: live  - an intraday quote from the current session
    #: close - a completed session's closing price (always the case when closed)
    #: none  - nothing known yet
    price_basis: PriceBasis
    as_of_session: date | None
    provider_time: datetime | None
    #: When our servers fetched the value shown. The UI's "last updated" source.
    fetched_at: datetime | None
    is_stale: bool
    sparkline: list[float]
    signal: SignalOut | None
    source: str | None


class MarketStatusOut(BaseModel):
    is_open: bool
    session: str
    reason: str | None
    last_completed_session: date
    next_open: datetime
    next_close: datetime | None


class DashboardOut(BaseModel):
    server_time: datetime
    last_updated_at: datetime | None
    market: MarketStatusOut
    data_status: DataStatus
    #: True when prices come from the built-in simulator. The UI must say so.
    is_simulated: bool
    provider: str
    refresh_interval_seconds: int
    #: A background fetch was started by this request; fresher data will follow.
    revalidating: bool = False
    rows: list[MarketRowOut]
