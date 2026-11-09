"""The bullish/bearish signal - the product's core claim (build plan section 4).

Deterministic by construction: the same bars in always give the same score out.
No LLM decides "bullish". Every snapshot stores its inputs and per-component
contributions, so any badge a user saw can be reproduced and explained later.

    score = 0.30 * price_vs_50dma_z
          + 0.20 * rsi14_normalized
          + 0.20 * return_5d_z
          + 0.15 * volume_vs_20d_avg_z
          + 0.15 * news_sentiment_7d        # clamped to [-1, 1]

Decisions the build plan leaves open, made explicit here so they can be reviewed:

1. Normalisation. The plan maps the score to [-100, +100] but mixes unbounded
   z-scores with bounded terms. Each z-score is clamped to [-3, 3] and divided by
   3; RSI maps 0..100 onto -1..1. Every component is then in [-1, 1], the weights
   sum to 1, so the score is exactly bounded by +/-100.

2. Volume direction. A raw volume z-score is not directional - heavy volume on a
   crash would read as *bullish*. The volume term is therefore signed by the
   session's price direction ("volume confirms the move"). Flip
   VOLUME_SIGNED_BY_DIRECTION to follow the plan literally. Needs client sign-off.

3. Missing news. Sentiment arrives with the Phase 3 feed. Until then the term
   contributes 0 and is marked unavailable, so the maximum reachable score is
   +/-85 and the hover breakdown says why.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import fmean, pstdev
from typing import Any, Literal

#: 2 - the news sentiment term went live with the Phase 3 feed. Snapshots
#: from version 1 scored it as unavailable, so old badges stay explainable.
FORMULA_VERSION = 2

WEIGHTS: dict[str, float] = {
    "price_vs_50dma_z": 0.30,
    "rsi14_normalized": 0.20,
    "return_5d_z": 0.20,
    "volume_vs_20d_avg_z": 0.15,
    "news_sentiment_7d": 0.15,
}

LABELS: dict[str, str] = {
    "price_vs_50dma_z": "Price vs 50-day average",
    "rsi14_normalized": "RSI (14)",
    "return_5d_z": "5-day return",
    "volume_vs_20d_avg_z": "Volume vs 20-day average",
    "news_sentiment_7d": "News sentiment (7d)",
}

Z_CLAMP = 3.0
SMA_WINDOW = 50
RSI_PERIOD = 14
RETURN_LAG = 5
RETURN_Z_WINDOW = 60
VOLUME_WINDOW = 20
VOLUME_SIGNED_BY_DIRECTION = True

#: Fewest daily bars that fill every window above.
MIN_HISTORY = max(SMA_WINDOW, RSI_PERIOD + 1, RETURN_LAG + RETURN_Z_WINDOW, VOLUME_WINDOW + 1)

Band = Literal["strong_bearish", "bearish", "neutral", "bullish", "strong_bullish"]


def band_for_score(score: float) -> Band:
    """Section 4 thresholds. Mirrored by bandForScore() in the web app; both are
    tested against shared/signal_bands.json so they cannot drift."""
    if score < -40:
        return "strong_bearish"
    if score < -15:
        return "bearish"
    if score <= 15:
        return "neutral"
    if score <= 40:
        return "bullish"
    return "strong_bullish"


# ---------------------------------------------------------------------------
# Indicators - small, pure, individually tested
# ---------------------------------------------------------------------------


def z_score(value: float, population: Sequence[float]) -> float:
    """Population z-score. A flat population has no spread, so the answer is 0."""
    if len(population) < 2:
        return 0.0
    spread = pstdev(population)
    if spread == 0 or math.isnan(spread):
        return 0.0
    return (value - fmean(population)) / spread


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalise_z(z: float) -> float:
    return clamp(z, -Z_CLAMP, Z_CLAMP) / Z_CLAMP


def rsi_wilder(closes: Sequence[float], period: int = RSI_PERIOD) -> float:
    """Wilder's RSI over the whole series. Requires period + 1 closes."""
    if len(closes) < period + 1:
        raise ValueError(f"RSI({period}) needs at least {period + 1} closes")

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]

    avg_gain = fmean(gains[:period])
    avg_loss = fmean(losses[:period])
    for gain, loss in zip(gains[period:], losses[period:], strict=True):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 50.0 if avg_gain == 0 else 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


# ---------------------------------------------------------------------------
# The composite
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignalResult:
    score: float
    band: Band
    components: dict[str, dict[str, Any]]
    inputs: dict[str, Any]
    formula_version: int = FORMULA_VERSION
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "formula_version": self.formula_version,
            "components": self.components,
            "inputs": self.inputs,
            "notes": self.notes,
        }


def compute_signal(
    closes: Sequence[float],
    volumes: Sequence[float],
    news_sentiment_7d: float | None = None,
) -> SignalResult | None:
    """Score one ticker from ascending daily closes and volumes.

    The last element is the most recent point - the caller may substitute a live
    price for today's close. Returns None when history is too short to fill every
    window: no signal is better than a signal built on half a window.
    """
    if len(closes) != len(volumes):
        raise ValueError("closes and volumes must be the same length")
    if len(closes) < MIN_HISTORY:
        return None
    if any(c <= 0 for c in closes):
        raise ValueError("closes must be positive")

    last = closes[-1]
    notes: list[str] = []

    # 1. Price vs 50-day moving average, as a z-score within that window.
    sma_window = list(closes[-SMA_WINDOW:])
    sma50 = fmean(sma_window)
    price_z = z_score(last, sma_window)

    # 2. RSI(14) mapped from 0..100 onto -1..1.
    rsi14 = rsi_wilder(closes)
    rsi_norm = (rsi14 - 50.0) / 50.0

    # 3. Latest 5-day return against the distribution of recent 5-day returns.
    returns = [closes[i] / closes[i - RETURN_LAG] - 1.0 for i in range(RETURN_LAG, len(closes))][
        -RETURN_Z_WINDOW:
    ]
    return_5d = returns[-1]
    return_z = z_score(return_5d, returns)

    # 4. Latest volume against the 20 sessions before it.
    prior_volumes = list(volumes[-VOLUME_WINDOW - 1 : -1])
    volume_z = z_score(volumes[-1], prior_volumes)
    direction = (last > closes[-2]) - (last < closes[-2])
    volume_norm = normalise_z(volume_z)
    if VOLUME_SIGNED_BY_DIRECTION:
        volume_norm *= direction

    # 5. News sentiment (Phase 3).
    news_available = news_sentiment_7d is not None
    news_norm = clamp(news_sentiment_7d, -1.0, 1.0) if news_sentiment_7d is not None else 0.0
    if not news_available:
        notes.append("No scored news in the last 7 days; counted as neutral.")

    raw = {
        "price_vs_50dma_z": price_z,
        "rsi14_normalized": rsi14,
        "return_5d_z": return_z,
        "volume_vs_20d_avg_z": volume_z,
        "news_sentiment_7d": news_sentiment_7d,
    }
    normalised = {
        "price_vs_50dma_z": normalise_z(price_z),
        "rsi14_normalized": rsi_norm,
        "return_5d_z": normalise_z(return_z),
        "volume_vs_20d_avg_z": volume_norm,
        "news_sentiment_7d": news_norm,
    }

    components: dict[str, dict[str, Any]] = {}
    total = 0.0
    for key, weight in WEIGHTS.items():
        raw_value = raw[key]
        contribution = 100.0 * weight * normalised[key]
        total += contribution
        components[key] = {
            "label": LABELS[key],
            "weight": weight,
            "raw": None if raw_value is None else round(float(raw_value), 4),
            "normalized": round(normalised[key], 4),
            "contribution": round(contribution, 2),
            "available": key != "news_sentiment_7d" or news_available,
        }

    score = round(clamp(total, -100.0, 100.0), 1)
    return SignalResult(
        score=score,
        band=band_for_score(score),
        components=components,
        inputs={
            "last_price": round(last, 4),
            "previous_close": round(closes[-2], 4),
            "sma50": round(sma50, 4),
            "rsi14": round(rsi14, 2),
            "return_5d": round(return_5d, 6),
            "last_volume": volumes[-1],
            "bars_used": len(closes),
            "volume_signed_by_direction": VOLUME_SIGNED_BY_DIRECTION,
        },
        notes=notes,
    )
