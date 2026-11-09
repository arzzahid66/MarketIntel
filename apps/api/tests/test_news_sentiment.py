"""The news half of the signal: prompt contract, reply validation, aggregation.

The rule these protect is the build plan's: an LLM may read a headline, but it
may never produce the signal. Everything here converts model text into one
bounded number that `compute_signal` weights at 0.15 - and refuses to produce a
number at all when the reply cannot be trusted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.llm.base import LLMRefused, LLMResponse
from app.llm.fake import FakeLLM
from app.services import signals as signal_engine
from app.services.news_sentiment import (
    LOOKBACK_DAYS,
    MATERIALITY_WEIGHT,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    Article,
    ArticleSentiment,
    ScoredArticle,
    aggregate_7d,
    build_user_prompt,
    parse_sentiment,
    score_article,
)

NOW = datetime(2026, 9, 28, 16, 0, tzinfo=UTC)


def article(headline: str, days_ago: float = 0.0, summary: str | None = None) -> Article:
    return Article(
        headline=headline,
        summary=summary,
        url=f"https://example.com/{abs(hash(headline))}",
        publisher="Example Wire",
        published_at=NOW - timedelta(days=days_ago),
    )


def scored(
    headline: str,
    score: float,
    days_ago: float = 0.0,
    materiality: str = "high",
) -> ScoredArticle:
    return ScoredArticle(
        article=article(headline, days_ago),
        sentiment=ArticleSentiment(
            score=score,
            label="neutral",
            materiality=materiality,
            rationale="",
            model="test",
            prompt_version=1,
        ),
    )


# ---------------------------------------------------------------------------
# The prompt contract
# ---------------------------------------------------------------------------


class TestPrompt:
    def test_forbids_recommendations(self) -> None:
        """Rule: the product shows direction, never buy/sell/hold advice."""
        assert "Never output a recommendation to buy, sell or hold." in SYSTEM_PROMPT

    def test_forbids_scoring_price_moves_as_news(self) -> None:
        """Price is already 0.85 of the formula; scoring it here double-counts it."""
        assert "A price movement is not news." in SYSTEM_PROMPT

    def test_forbids_outside_knowledge_and_invention(self) -> None:
        assert "never invent facts" in SYSTEM_PROMPT
        assert "Do not use outside knowledge" in SYSTEM_PROMPT

    def test_user_prompt_carries_what_the_model_needs_and_nothing_else(self) -> None:
        prompt = build_user_prompt(article("Apple beats on earnings"), "Apple Inc.", "AAPL")
        assert "Apple Inc. (AAPL)" in prompt
        assert "Apple beats on earnings" in prompt
        assert "2026-09-28" in prompt
        assert "(none provided)" in prompt  # missing summary is stated, not faked


# ---------------------------------------------------------------------------
# Reply validation
# ---------------------------------------------------------------------------


class TestParsing:
    def test_reads_a_clean_reply(self) -> None:
        text = '{"sentiment": 0.8, "label": "positive", "materiality": "high", "rationale": "B."}'
        result = parse_sentiment(text, "m")
        assert (result.score, result.label, result.materiality) == (0.8, "positive", "high")
        assert result.prompt_version == PROMPT_VERSION

    def test_survives_code_fences_and_preamble(self) -> None:
        text = 'Sure!\n```json\n{"sentiment": -0.5, "materiality": "high"}\n```'
        assert parse_sentiment(text, "m").score == -0.5

    @pytest.mark.parametrize("raw,expected", [(5.0, 1.0), (-9.9, -1.0)])
    def test_clamps_a_score_outside_the_range(self, raw: float, expected: float) -> None:
        """The term is weighted as if bounded; an unclamped 5.0 would blow the score."""
        assert parse_sentiment(f'{{"sentiment": {raw}}}', "m").score == expected

    @pytest.mark.parametrize(
        "text",
        [
            "I cannot score this.",
            '{"sentiment": "very good"}',
            '{"sentiment": true}',
            '{"label": "positive"}',
            "[1, 2, 3]",
        ],
    )
    def test_refuses_a_reply_it_cannot_trust(self, text: str) -> None:
        """No number is better than a guessed one - the caller skips the article."""
        with pytest.raises(LLMRefused):
            parse_sentiment(text, "m")

    def test_an_unknown_materiality_quietens_rather_than_drops(self) -> None:
        result = parse_sentiment('{"sentiment": 0.9, "materiality": "enormous"}', "m")
        assert result.materiality == "low"

    def test_derives_a_missing_label_from_the_score(self) -> None:
        assert parse_sentiment('{"sentiment": -0.7}', "m").label == "negative"
        assert parse_sentiment('{"sentiment": 0.0}', "m").label == "neutral"


# ---------------------------------------------------------------------------
# Aggregation into the signal's term
# ---------------------------------------------------------------------------


class TestAggregation:
    def test_no_news_is_not_neutral_news(self) -> None:
        """None marks the component unavailable; 0.0 would silently vote neutral."""
        assert aggregate_7d([], NOW) is None

    def test_ignores_articles_older_than_the_window(self) -> None:
        assert aggregate_7d([scored("Old", 1.0, days_ago=LOOKBACK_DAYS + 1)], NOW) is None

    def test_recent_news_outweighs_week_old_news(self) -> None:
        board = aggregate_7d([scored("Fresh", 1.0, 0.0), scored("Stale", -1.0, 6.0)], NOW)
        assert board is not None and board > 0.5

    def test_one_material_event_outweighs_a_wall_of_filler(self) -> None:
        filler = [scored(f"Routine {i}", 0.5, 0.0, materiality="low") for i in range(6)]
        result = aggregate_7d([*filler, scored("Fraud probe", -1.0, 0.0)], NOW)
        assert result is not None and result < 0.0

    def test_stays_inside_the_range_the_formula_assumes(self) -> None:
        mixed = [scored("C", 1.0), scored("D", -1.0)]
        for items in ([scored("A", 1.0)], [scored("B", -1.0)], mixed):
            value = aggregate_7d(items, NOW)
            assert value is not None and -1.0 <= value <= 1.0

    def test_a_future_dated_article_is_treated_as_new_not_negative_aged(self) -> None:
        """A publisher dating ahead must not get a weight above a fresh article."""
        assert aggregate_7d([scored("Ahead", 1.0, days_ago=-2.0)], NOW) == 1.0

    def test_materiality_bands_are_ordered(self) -> None:
        assert MATERIALITY_WEIGHT["high"] > MATERIALITY_WEIGHT["medium"] > MATERIALITY_WEIGHT["low"]


# ---------------------------------------------------------------------------
# End to end, and the seam into the deterministic signal
# ---------------------------------------------------------------------------


class TestIntoTheSignal:
    def test_the_fake_client_satisfies_the_contract_without_a_key(self) -> None:
        sentiment = score_article(FakeLLM(), article("Company faces fraud probe"), "X Inc.", "X")
        assert -1.0 <= sentiment.score <= 1.0
        assert sentiment.score < 0

    def test_the_same_article_scores_the_same_way_twice(self) -> None:
        """A signal a customer saw has to be reproducible."""
        item = article("Company beats guidance and raises outlook")
        first = score_article(FakeLLM(), item, "X Inc.", "X")
        second = score_article(FakeLLM(), item, "X Inc.", "X")
        assert first == second

    def test_a_refusal_propagates_so_the_caller_can_skip_the_article(self) -> None:
        class Broken:
            name, model, is_simulated = "broken", "broken", True

            def complete(
                self,
                system: str,
                user: str,
                *,
                max_tokens: int = 512,
                json_object: bool = False,
            ) -> LLMResponse:
                return LLMResponse(text="I'd rather not.", model=self.model)

        with pytest.raises(LLMRefused):
            score_article(Broken(), article("Anything"), "X Inc.", "X")

    def test_sentiment_reaches_the_signal_and_flips_the_component_to_available(self) -> None:
        """The whole point of the module: one bounded number into the 0.15 term."""
        closes = [100.0 + i * 0.1 for i in range(signal_engine.MIN_HISTORY)]
        volumes = [1_000_000.0] * signal_engine.MIN_HISTORY

        without = signal_engine.compute_signal(closes, volumes)
        with_news = signal_engine.compute_signal(closes, volumes, news_sentiment_7d=-1.0)
        assert without is not None and with_news is not None

        assert without.components["news_sentiment_7d"]["available"] is False
        assert with_news.components["news_sentiment_7d"]["available"] is True
        # 0.15 weight, fully negative: 15 points below the no-news score.
        assert with_news.score == pytest.approx(without.score - 15.0, abs=0.01)
