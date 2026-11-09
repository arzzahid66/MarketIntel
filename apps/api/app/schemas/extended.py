"""Wire types for the extended-markets surface (Phase 5)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

#: The two values of the `markets.extended_access` plan feature.
Access = Literal["full", "delayed"]


class ConstituentOut(BaseModel):
    symbol: str
    name: str
    market_cap: float | None
    change_percent: float | None
    price: float | None
    is_big7: bool


class SectorTileOut(BaseModel):
    sector: str
    #: Market-cap weighted. None means "not computable", not 0% - the UI must
    #: render those differently or an unknown tile reads as a flat one.
    change_percent: float | None
    market_cap: float
    #: 0..1 colour saturation; the sign of `change_percent` gives direction.
    intensity: float
    count: int
    weighted_count: int
    #: Empty on a `delayed` plan: the sector picture without the per-name
    #: breakdown. Absent from the payload entirely rather than hidden in the UI.
    constituents: list[ConstituentOut]


class HeatmapOut(BaseModel):
    server_time: datetime
    access: Access
    tiles: list[SectorTileOut]
    is_simulated: bool
    #: Names with a price, over names we tried to render. A tile built from a
    #: fraction of its sector is one to distrust, so the ratio is in the payload.
    covered: int
    total: int


class EarningsEventOut(BaseModel):
    symbol: str
    name: str | None
    session_date: date
    #: "bmo", "amc", or "" when the source does not say.
    timing: str
    fiscal_quarter: int | None
    fiscal_year: int | None
    eps_estimate: float | None
    eps_actual: float | None
    revenue_estimate: float | None
    revenue_actual: float | None
    source: str


class CalendarOut(BaseModel):
    server_time: datetime
    access: Access
    since: date
    until: date
    #: The window a `full` plan would return. Lets the upgrade prompt state what
    #: is actually behind the paywall instead of guessing at it.
    full_until: date
    events: list[EarningsEventOut]


class UniverseRowOut(BaseModel):
    symbol: str
    name: str
    sector: str | None
    industry: str | None
    exchange: str | None
    market_cap: float | None
    price: float | None
    change_percent: float | None
    is_big7: bool
    source: str | None


class UniverseOut(BaseModel):
    server_time: datetime
    access: Access
    rows: list[UniverseRowOut]
    is_simulated: bool
