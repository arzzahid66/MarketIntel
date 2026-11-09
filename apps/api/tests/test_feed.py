"""The feed pipeline: ingest, dedup, scoring, and the seam into the signal.

The rules being protected are the Phase 3 cost and honesty rules: a story is
stored once, scored once per company, and never re-scored on read; a company
with no news reads as unavailable rather than neutral; and every stored row
carries the citation fields rule 4 requires.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.llm.base import LLMError, LLMResponse
from app.llm.fake import FakeLLM
from app.models.feed import FeedItem, FeedItemTicker
from app.services import feed as feed_service
from app.services import market_data as md
from app.sources.base import RawArticle, SourceError

NOW = datetime(2026, 10, 5, 16, 0, tzinfo=UTC)


class ListSource:
    """A source returning exactly what a test hands it."""

    name = "test-source"

    def __init__(self, articles: list[RawArticle], fail: bool = False) -> None:
        self.articles = articles
        self.fail = fail
        self.calls = 0

    def fetch(self, symbol: str, since, until) -> list[RawArticle]:
        self.calls += 1
        if self.fail:
            raise SourceError(self.name, "simulated outage")
        return self.articles


def article(title: str, url: str, minutes_ago: int = 0, publisher: str = "Wire") -> RawArticle:
    return RawArticle(
        title=title,
        summary="A summary.",
        url=url,
        publisher=publisher,
        published_at=NOW - timedelta(minutes=minutes_ago),
    )


# ---------------------------------------------------------------------------
# Ingest and dedup
# ---------------------------------------------------------------------------


class TestIngest:
    def test_stores_the_citation_fields_rule_four_requires(self, db: Session) -> None:
        tickers = md.big7_tickers(db)[:1]
        source = ListSource([article("Apple beats earnings", "https://e.com/a")])

        feed_service.ingest_news(db, source, tickers, NOW)

        item = db.scalars(select(FeedItem)).one()
        assert item.source_url == "https://e.com/a"
        assert item.publisher == "Wire"
        assert item.fetched_at == NOW
        assert item.source == "test-source"

    def test_the_same_url_twice_is_one_row(self, db: Session) -> None:
        tickers = md.big7_tickers(db)[:1]
        source = ListSource([article("Apple beats earnings", "https://e.com/a")])

        feed_service.ingest_news(db, source, tickers, NOW)
        result = feed_service.ingest_news(db, source, tickers, NOW)

        assert db.scalar(select(func.count(FeedItem.id))) == 1
        assert result.inserted == 0
        assert result.duplicates == 1

    def test_tracking_parameters_do_not_create_a_second_row(self, db: Session) -> None:
        tickers = md.big7_tickers(db)[:1]
        source = ListSource(
            [
                article("Apple beats earnings", "https://e.com/a"),
                article("Apple beats earnings", "https://e.com/a?utm_source=email"),
            ]
        )

        feed_service.ingest_news(db, source, tickers, NOW)

        assert db.scalar(select(func.count(FeedItem.id))) == 1

    def test_a_syndicated_story_under_another_url_is_one_row(self, db: Session) -> None:
        """What the URL key cannot catch: same story, different publisher."""
        tickers = md.big7_tickers(db)[:1]
        source = ListSource(
            [
                article("Nvidia and Groq sign $20 billion licensing deal", "https://a.com/1"),
                article(
                    "Nvidia and Groq sign $20 billion licensing deal - report",
                    "https://b.com/2",
                    publisher="Other Wire",
                ),
            ]
        )

        result = feed_service.ingest_news(db, source, tickers, NOW)

        assert db.scalar(select(func.count(FeedItem.id))) == 1
        assert result.duplicates == 1

    def test_one_story_about_two_companies_is_stored_once_and_linked_twice(
        self, db: Session
    ) -> None:
        """Dedup must not cost the second company its link to the story."""
        tickers = md.big7_tickers(db)[:2]
        source = ListSource([article("Apple and Microsoft announce a deal", "https://e.com/a")])

        result = feed_service.ingest_news(db, source, tickers, NOW)

        assert db.scalar(select(func.count(FeedItem.id))) == 1
        assert db.scalar(select(func.count(FeedItemTicker.id))) == 2
        assert result.linked == 2

    def test_a_dead_source_is_reported_not_raised(self, db: Session) -> None:
        tickers = md.big7_tickers(db)[:1]
        result = feed_service.ingest_news(db, ListSource([], fail=True), tickers, NOW)

        assert result.failed
        assert result.inserted == 0

    def test_ingest_never_calls_the_model(self, db: Session) -> None:
        """Scoring is a separate job so a slow model cannot stall the feed."""

        class Exploding:
            name, model, is_simulated = "boom", "boom", True

            def complete(
                self,
                system: str,
                user: str,
                *,
                max_tokens: int = 512,
                json_object: bool = False,
            ) -> LLMResponse:
                raise AssertionError("ingest must not call the LLM")

        tickers = md.big7_tickers(db)[:1]
        feed_service.ingest_news(
            db,
            ListSource([article("Apple opens a new store in Berlin", "https://e.com/a")]),
            tickers,
            NOW,
        )

        link = db.scalars(select(FeedItemTicker)).one()
        assert link.scored_at is None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


class TestScoring:
    def test_scores_are_stored_with_the_model_and_prompt_version(self, db: Session) -> None:
        """A signal a customer saw has to be reproducible later."""
        tickers = md.big7_tickers(db)[:1]
        feed_service.ingest_news(
            db, ListSource([article("Company faces fraud probe", "https://e.com/a")]), tickers, NOW
        )

        result = feed_service.score_pending(db, FakeLLM(), NOW)

        link = db.scalars(select(FeedItemTicker)).one()
        assert result.scored == 1
        assert link.scored_at == NOW
        assert link.model and link.prompt_version
        assert link.sentiment is not None and -1.0 <= link.sentiment <= 1.0

    def test_an_article_is_never_scored_twice(self, db: Session) -> None:
        """Cost tracks news volume, not how often the job runs."""
        tickers = md.big7_tickers(db)[:1]
        feed_service.ingest_news(
            db, ListSource([article("Apple beats earnings", "https://e.com/a")]), tickers, NOW
        )

        class Counting(FakeLLM):
            calls = 0

            def complete(
                self,
                system: str,
                user: str,
                *,
                max_tokens: int = 512,
                json_object: bool = False,
            ) -> LLMResponse:
                type(self).calls += 1
                return super().complete(system, user, max_tokens=max_tokens)

        client = Counting()
        feed_service.score_pending(db, client, NOW)
        feed_service.score_pending(db, client, NOW)

        assert Counting.calls == 1

    def test_the_category_is_set_from_the_taxonomy_rows(self, db: Session) -> None:
        tickers = md.big7_tickers(db)[:1]
        feed_service.ingest_news(
            db,
            ListSource([article("Company reports record earnings", "https://e.com/a")]),
            tickers,
            NOW,
        )

        feed_service.score_pending(db, FakeLLM(), NOW)

        item = db.scalars(select(FeedItem)).one()
        assert item.classified_at == NOW
        assert item.category is not None
        assert item.category.key in {c.key for c in feed_service.categories(db)}

    def test_a_failing_article_is_counted_and_eventually_abandoned(self, db: Session) -> None:
        """One unparseable article must not be retried forever."""
        tickers = md.big7_tickers(db)[:1]
        feed_service.ingest_news(
            db,
            ListSource([article("Apple opens a new store in Berlin", "https://e.com/a")]),
            tickers,
            NOW,
        )

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
                raise LLMError(self.name, "always fails")

        for _ in range(5):
            feed_service.score_pending(db, Broken(), NOW, max_attempts=3)

        link = db.scalars(select(FeedItemTicker)).one()
        assert link.failed_attempts == 3  # stopped retrying
        assert link.last_error
        assert link.scored_at is None

    def test_a_batch_is_capped_so_one_cycle_cannot_run_away(self, db: Session) -> None:
        tickers = md.big7_tickers(db)[:1]
        # Deliberately unalike: near-duplicate titles would be merged at ingest
        # and this test would be measuring dedup instead of the batch cap.
        titles = [
            "Apple beats quarterly earnings expectations",
            "Microsoft opens a data centre in Dublin",
            "Tesla recalls vehicles over a steering fault",
            "Meta faces a European antitrust complaint",
            "Amazon raises its full year revenue guidance",
            "Nvidia signs a chip supply agreement",
            "Alphabet settles a long running patent dispute",
            "Oil prices climb after an OPEC production cut",
            "The Federal Reserve holds interest rates steady",
            "Bitcoin falls below a closely watched level",
        ]
        articles = [article(t, f"https://e.com/{i}", i) for i, t in enumerate(titles)]
        feed_service.ingest_news(db, ListSource(articles), tickers, NOW)

        result = feed_service.score_pending(db, FakeLLM(), NOW, limit=3)

        assert result.scored == 3


# ---------------------------------------------------------------------------
# Into the signal
# ---------------------------------------------------------------------------


class TestIntoTheSignal:
    def test_a_company_with_no_scored_news_is_absent_not_zero(self, db: Session) -> None:
        """compute_signal marks a missing value unavailable; 0.0 would vote neutral."""
        tickers = md.big7_tickers(db)
        result = feed_service.sentiment_for_tickers(db, [t.id for t in tickers], NOW)
        assert result == {}

    def test_scored_news_reaches_the_signal_as_a_bounded_number(self, db: Session) -> None:
        tickers = md.big7_tickers(db)[:1]
        feed_service.ingest_news(
            db,
            ListSource([article("Company faces fraud probe and lawsuit", "https://e.com/a")]),
            tickers,
            NOW,
        )
        feed_service.score_pending(db, FakeLLM(), NOW)

        values = feed_service.sentiment_for_tickers(db, [tickers[0].id], NOW)

        assert tickers[0].id in values
        assert -1.0 <= values[tickers[0].id] <= 1.0

    def test_news_outside_the_window_does_not_count(self, db: Session) -> None:
        tickers = md.big7_tickers(db)[:1]
        old = article("Company faces fraud probe", "https://e.com/a", minutes_ago=60 * 24 * 30)
        feed_service.ingest_news(db, ListSource([old]), tickers, NOW)
        feed_service.score_pending(db, FakeLLM(), NOW)

        assert feed_service.sentiment_for_tickers(db, [tickers[0].id], NOW) == {}


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


class TestReads:
    def test_the_feed_is_newest_first(self, db: Session) -> None:
        tickers = md.big7_tickers(db)[:1]
        titles = [
            "Apple beats quarterly earnings expectations again",
            "Microsoft opens a new data centre in Dublin",
            "Tesla recalls 400,000 vehicles over a steering fault",
            "Meta faces a European antitrust complaint",
        ]
        articles = [
            article(t, f"https://e.com/{i}", minutes_ago=i * 10) for i, t in enumerate(titles)
        ]
        feed_service.ingest_news(db, ListSource(articles), tickers, NOW)

        items = feed_service.recent_items(db, limit=10)

        assert [i.title for i in items] == titles

    def test_filtering_by_symbol_returns_only_that_company(self, db: Session) -> None:
        apple, microsoft = md.big7_tickers(db)[:2]
        feed_service.ingest_news(
            db,
            ListSource([article("Apple opens a new store in Berlin", "https://e.com/a")]),
            [apple],
            NOW,
        )
        feed_service.ingest_news(
            db,
            ListSource([article("Microsoft launches a cloud region", "https://e.com/b")]),
            [microsoft],
            NOW,
        )

        items = feed_service.recent_items(db, symbol=apple.symbol)

        assert [i.title for i in items] == ["Apple opens a new store in Berlin"]


class TestDuplicateRateMeasurement:
    """The Phase 3 exit criterion is duplicates that *survive* into the feed,
    not duplicates the pipeline caught on the way in. The two numbers move in
    opposite directions: a noisy source raises the caught rate (good) while the
    surviving rate should stay near zero."""

    def test_a_clean_feed_measures_near_zero(self, db: Session) -> None:
        tickers = md.big7_tickers(db)[:1]
        titles = [
            "Apple beats quarterly earnings expectations",
            "Microsoft opens a data centre in Dublin",
            "Tesla recalls vehicles over a steering fault",
            "Meta faces a European antitrust complaint",
        ]
        articles = [article(t, f"https://e.com/{i}") for i, t in enumerate(titles)]
        feed_service.ingest_news(db, ListSource(articles), tickers, NOW)

        rate, duplicates, sampled = feed_service.surviving_duplicate_rate(db, NOW)

        assert sampled == len(titles)
        assert duplicates == 0 and rate == 0.0

    def test_syndication_is_caught_on_the_way_in_so_it_never_survives(self, db: Session) -> None:
        tickers = md.big7_tickers(db)[:1]
        feed_service.ingest_news(
            db,
            ListSource(
                [
                    article("Nvidia and Groq sign a $20 billion licensing deal", "https://a/1"),
                    article(
                        "Nvidia and Groq sign a $20 billion licensing deal - report",
                        "https://b/2",
                    ),
                ]
            ),
            tickers,
            NOW,
        )

        rate, _, sampled = feed_service.surviving_duplicate_rate(db, NOW)

        assert sampled == 1  # the syndicated copy never became a row
        assert rate == 0.0

    def test_a_looser_threshold_is_how_the_production_one_is_audited(self, db: Session) -> None:
        """Measured at the ingest threshold the result is self-confirming, so the
        audit runs it wider. Two headlines sharing a template but naming different
        companies must stay separate - merging them would hide a real article."""
        tickers = md.big7_tickers(db)[:1]
        feed_service.ingest_news(
            db,
            ListSource(
                [
                    article("Should you buy Amazon stock before October 29", "https://a/1"),
                    article("Should you buy Costco stock before October 30", "https://b/2"),
                ]
            ),
            tickers,
            NOW,
        )

        at_production, _, sampled = feed_service.surviving_duplicate_rate(db, NOW)
        assert sampled == 2 and at_production == 0.0
