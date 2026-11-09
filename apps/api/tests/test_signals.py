"""The signal is the product's core claim, so its maths is tested piece by piece."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.services import signals as S

SHARED = Path(__file__).resolve().parents[3] / "shared" / "signal_bands.json"


def trend(n: int, start: float = 100.0, step: float = 0.01) -> list[float]:
    """A steady compounding trend with a small alternating wobble."""
    return [start * (1 + step) ** i * (1 + (0.002 if i % 2 else -0.002)) for i in range(n)]


def flat_volumes(n: int, value: float = 1_000_000) -> list[float]:
    return [value * (1 + (0.05 if i % 3 == 0 else -0.02)) for i in range(n)]


# --------------------------------------------------------------------------
# Bands - shared with the web app
# --------------------------------------------------------------------------


def test_bands_match_the_shared_fixture() -> None:
    cases = json.loads(SHARED.read_text(encoding="utf-8"))["cases"]
    assert cases, "shared fixture is empty"
    for case in cases:
        assert S.band_for_score(case["score"]) == case["band"], case


def test_weights_sum_to_one_so_the_score_is_bounded_by_100() -> None:
    assert math.isclose(sum(S.WEIGHTS.values()), 1.0)
    assert set(S.WEIGHTS) == set(S.LABELS)


# --------------------------------------------------------------------------
# Indicators
# --------------------------------------------------------------------------


def test_rsi_is_fifty_when_gains_equal_losses() -> None:
    closes = [100.0]
    for change in [1] * 7 + [-1] * 7:
        closes.append(closes[-1] + change)
    assert S.rsi_wilder(closes) == pytest.approx(50.0)


def test_rsi_matches_the_closed_form_for_a_two_to_one_ratio() -> None:
    closes = [100.0]
    for change in [2] * 7 + [-1] * 7:
        closes.append(closes[-1] + change)
    # avg gain 1.0, avg loss 0.5 -> RS 2 -> RSI 100 - 100/3
    assert S.rsi_wilder(closes) == pytest.approx(200 / 3)


def test_rsi_extremes() -> None:
    assert S.rsi_wilder([float(i) for i in range(1, 30)]) == 100.0
    assert S.rsi_wilder([100.0] * 20) == 50.0


def test_rsi_needs_period_plus_one_closes() -> None:
    with pytest.raises(ValueError):
        S.rsi_wilder([1.0] * 14)


def test_z_score_of_a_flat_series_is_zero_not_nan() -> None:
    assert S.z_score(5.0, [5.0] * 20) == 0.0
    assert S.z_score(5.0, [5.0]) == 0.0


def test_z_scores_are_clamped_before_weighting() -> None:
    assert S.normalise_z(10.0) == 1.0
    assert S.normalise_z(-10.0) == -1.0
    assert S.normalise_z(1.5) == pytest.approx(0.5)


# --------------------------------------------------------------------------
# The composite
# --------------------------------------------------------------------------


def test_insufficient_history_gives_no_signal_rather_than_a_guess() -> None:
    n = S.MIN_HISTORY - 1
    assert S.compute_signal(trend(n), flat_volumes(n)) is None


def test_uptrend_scores_bullish_and_downtrend_scores_bearish() -> None:
    n = 120
    up = S.compute_signal(trend(n, step=0.01), flat_volumes(n))
    down = S.compute_signal(trend(n, step=-0.01), flat_volumes(n))
    assert up is not None and down is not None
    assert up.score > 15 and up.band in ("bullish", "strong_bullish")
    assert down.score < -15 and down.band in ("bearish", "strong_bearish")


def test_without_news_the_score_cannot_exceed_85() -> None:
    n = 120
    closes = trend(n, step=0.03)
    closes[-1] *= 1.5  # a violent final move to saturate every price component
    volumes = flat_volumes(n)
    volumes[-1] *= 20
    result = S.compute_signal(closes, volumes)
    assert result is not None
    assert result.score <= 85.0
    news = result.components["news_sentiment_7d"]
    assert news["available"] is False and news["contribution"] == 0
    # The breakdown has to say why the term is missing, not just drop it. Since
    # the feed went live, "no news" means none was scored in the window rather
    # than the feature not existing yet.
    assert any("No scored news" in note for note in result.notes)


def test_news_sentiment_is_clamped_and_can_lift_the_score_past_85() -> None:
    n = 120
    closes = trend(n, step=0.03)
    closes[-1] *= 1.5
    volumes = flat_volumes(n)
    volumes[-1] *= 20
    result = S.compute_signal(closes, volumes, news_sentiment_7d=7.0)
    assert result is not None
    assert result.components["news_sentiment_7d"]["normalized"] == 1.0
    assert 85.0 < result.score <= 100.0


def test_heavy_volume_on_a_down_day_is_bearish_not_bullish() -> None:
    n = 120
    closes = trend(n, step=0.0)
    closes[-1] = closes[-2] * 0.95
    volumes = flat_volumes(n)
    volumes[-1] *= 10
    result = S.compute_signal(closes, volumes)
    assert result is not None
    assert S.VOLUME_SIGNED_BY_DIRECTION
    assert result.components["volume_vs_20d_avg_z"]["contribution"] < 0


def test_same_inputs_always_give_the_same_signal() -> None:
    n = 100
    a = S.compute_signal(trend(n), flat_volumes(n))
    b = S.compute_signal(trend(n), flat_volumes(n))
    assert a == b


def test_breakdown_explains_itself() -> None:
    n = 100
    result = S.compute_signal(trend(n), flat_volumes(n))
    assert result is not None
    assert set(result.components) == set(S.WEIGHTS)
    total = sum(c["contribution"] for c in result.components.values())
    assert total == pytest.approx(result.score, abs=0.1)
    for component in result.components.values():
        assert {"label", "weight", "raw", "normalized", "contribution", "available"} <= set(
            component
        )
    assert result.inputs["bars_used"] == n
    assert result.to_json()["formula_version"] == S.FORMULA_VERSION


def test_mismatched_or_invalid_series_are_rejected() -> None:
    with pytest.raises(ValueError):
        S.compute_signal(trend(80), flat_volumes(79))
    closes = trend(80)
    closes[10] = 0.0
    with pytest.raises(ValueError):
        S.compute_signal(closes, flat_volumes(80))
