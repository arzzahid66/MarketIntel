"""The AI analyst: retrieval, grounding, citations and the quota.

The rules being protected here are the ones with real consequences if they slip:
an answer must come only from retrieved articles, it must carry citations the
reader can check, and the plan's message allowance must be counted server-side
from the database rather than trusted from anywhere else.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.analyst import get_llm
from app.core.clock import fixed_clock, get_clock
from app.llm.base import LLMError, LLMResponse
from app.llm.fake import FakeLLM
from app.main import app
from app.models.analyst import AiMessage
from app.models.user import User
from app.services import analyst as analyst_service
from app.services import feed as feed_service
from app.services import market_data as md
from tests.conftest import auth_headers, signup
from tests.test_feed import ListSource, article

NOW = datetime(2026, 10, 19, 16, 0, tzinfo=UTC)


def use(now: datetime = NOW, client_impl=None):
    app.dependency_overrides[get_clock] = lambda: fixed_clock(now)
    llm = client_impl or FakeLLM()
    app.dependency_overrides[get_llm] = lambda: llm
    return llm


#: FakeLLM embeds lexically, not semantically - it cannot know "what about
#: nvidia" is about a licensing article. Questions here therefore share words
#: with the articles, so retrieval clears MAX_DISTANCE. A real embedding model
#: does not need the overlap; the stub does.
MATCHING_QUESTION = "nvidia chip licensing agreement"


def stock_the_feed(db: Session, titles: list[str], now: datetime = NOW) -> None:
    """Ingest, score and embed some articles so retrieval has something to find."""
    tickers = md.big7_tickers(db)[:1]
    articles = [article(t, f"https://e.com/{i}") for i, t in enumerate(titles)]
    feed_service.ingest_news(db, ListSource(articles), tickers, now)
    llm = FakeLLM()
    feed_service.score_pending(db, llm, now, limit=50)
    feed_service.embed_pending(db, llm, now, limit=50)


def a_user(db: Session) -> User:
    user = User(email="analyst@example.com", password_hash="x", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Retrieval and grounding
# ---------------------------------------------------------------------------


class TestRetrieval:
    def test_finds_the_article_about_the_question(self, db: Session) -> None:
        stock_the_feed(
            db,
            [
                "Nvidia signs a large chip licensing agreement",
                "Oil prices climb after an OPEC production cut",
                "The Federal Reserve holds interest rates steady",
            ],
        )

        found = analyst_service.retrieve(
            db, FakeLLM(), "nvidia chip licensing agreement", NOW, max_distance=2.0
        )

        assert found, "retrieval returned nothing"
        assert "Nvidia" in found[0].title

    def test_articles_without_an_embedding_are_invisible(self, db: Session) -> None:
        """The embed job lags ingest; an unembedded article is simply not yet
        searchable rather than silently breaking the query."""
        tickers = md.big7_tickers(db)[:1]
        feed_service.ingest_news(
            db,
            ListSource([article("Nvidia signs a licensing agreement", "https://e.com/1")]),
            tickers,
            NOW,
        )

        assert analyst_service.retrieve(db, FakeLLM(), "nvidia licensing", NOW) == []

    def test_articles_outside_the_window_are_not_retrieved(self, db: Session) -> None:
        stock_the_feed(db, ["Nvidia signs a large chip licensing agreement"])
        much_later = NOW + timedelta(days=analyst_service.RETRIEVE_WINDOW_DAYS + 5)

        assert analyst_service.retrieve(db, FakeLLM(), "nvidia licensing", much_later) == []

    def test_an_empty_feed_yields_the_honest_answer_not_a_guess(self, db: Session) -> None:
        user = a_user(db)

        answer = analyst_service.ask(db, FakeLLM(), user.id, "What about Nvidia?", NOW)

        assert answer.retrieved == 0
        assert answer.text == analyst_service.NO_CONTEXT_ANSWER
        assert answer.citations == []


class TestPrompt:
    def test_it_forbids_recommendations(self) -> None:
        assert "Never recommend buying, selling or holding" in analyst_service.SYSTEM_PROMPT

    def test_it_forbids_answering_from_memory(self) -> None:
        assert "Use only the provided articles" in analyst_service.SYSTEM_PROMPT
        assert "never invent a figure" in analyst_service.SYSTEM_PROMPT

    def test_it_requires_a_citation_on_every_factual_claim(self) -> None:
        assert "Every factual sentence needs a citation" in analyst_service.SYSTEM_PROMPT

    def test_the_context_numbering_matches_the_citations(self, db: Session) -> None:
        """The model cites [3]; [3] must resolve to the third article shown."""
        stock_the_feed(db, ["Nvidia news one", "Nvidia news two", "Nvidia news three"])
        items = analyst_service.retrieve(db, FakeLLM(), "nvidia", NOW, max_distance=2.0)

        context, citations = analyst_service.build_context(items)

        for citation in citations:
            assert f"[{citation.number}]" in context
            assert citation.title in context
            # Rule 4 reaching the reader: the citation can be clicked through.
            assert citation.source_url
            assert citation.publisher


class TestCitations:
    def test_only_the_cited_articles_are_returned(self, db: Session) -> None:
        """Listing sources the answer never used would overstate its grounding."""
        stock_the_feed(db, [f"Nvidia story number {i} about chips" for i in range(4)])
        user = a_user(db)

        class CitesOnlyTwo(FakeLLM):
            def complete(self, system, user, *, max_tokens=512, json_object=False):
                return LLMResponse(text="Something happened [2].", model="test-model")

        answer = analyst_service.ask(db, CitesOnlyTwo(), user.id, "nvidia story chips about", NOW)

        assert [c.number for c in answer.citations] == [2]
        assert answer.retrieved > 1

    def test_the_question_and_its_citations_are_recorded(self, db: Session) -> None:
        """The audit trail: what was said, and what it was said from."""
        stock_the_feed(db, ["Nvidia signs a chip licensing agreement"])
        user = a_user(db)

        class CitesOne(FakeLLM):
            def complete(self, system, user, *, max_tokens=512, json_object=False):
                return LLMResponse(text="Nvidia signed a deal [1].", model="test-model")

        analyst_service.ask(db, CitesOne(), user.id, MATCHING_QUESTION, NOW)

        row = db.scalars(select(AiMessage)).one()
        assert row.question == MATCHING_QUESTION
        assert row.model == "test-model"
        assert row.citations_json[0]["source_url"]
        assert row.prompt_version == analyst_service.PROMPT_VERSION


# ---------------------------------------------------------------------------
# The endpoint: entitlement, quota, failure
# ---------------------------------------------------------------------------


class TestEndpoint:
    def test_anonymous_visitors_cannot_spend_our_money(self, client: TestClient) -> None:
        use()
        assert client.post("/ai/ask", json={"question": "anything at all"}).status_code == 401

    def test_a_free_user_can_ask_and_sees_their_remaining_allowance(
        self, client: TestClient, db: Session
    ) -> None:
        stock_the_feed(db, ["Nvidia signs a chip licensing agreement"])
        use()
        tokens = signup(client, "free@example.com")

        response = client.post(
            "/ai/ask", json={"question": MATCHING_QUESTION}, headers=auth_headers(tokens)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["usage"]["daily_limit"] == 5  # the Free row of the plan matrix
        assert body["usage"]["used_today"] == 1
        assert body["model"]

    def test_the_daily_allowance_is_enforced_and_returns_402(
        self, client: TestClient, db: Session
    ) -> None:
        """402, not 403: they may be here, they need a bigger plan."""
        stock_the_feed(db, ["Nvidia signs a chip licensing agreement"])
        use()
        tokens = signup(client, "capped@example.com")
        headers = auth_headers(tokens)

        for _ in range(5):
            spent = client.post("/ai/ask", json={"question": MATCHING_QUESTION}, headers=headers)
            assert spent.status_code == 200

        blocked = client.post("/ai/ask", json={"question": MATCHING_QUESTION}, headers=headers)

        assert blocked.status_code == 402
        detail = blocked.json()["detail"]
        assert detail["error"] == "quota_exceeded"
        assert detail["used"] == 5 and detail["limit"] == 5

    def test_the_quota_counts_rows_so_it_survives_a_cache_flush(
        self, client: TestClient, db: Session
    ) -> None:
        """Counted in Postgres, not Redis. A quota that resets on a cache
        restart is not a quota."""
        stock_the_feed(db, ["Nvidia signs a chip licensing agreement"])
        use()
        tokens = signup(client, "counted@example.com")
        headers = auth_headers(tokens)
        client.post("/ai/ask", json={"question": MATCHING_QUESTION}, headers=headers)

        from app.core.redis import get_redis

        redis_client = get_redis()
        if redis_client is not None:
            redis_client.flushdb()

        status = client.get("/ai/status", headers=headers).json()
        assert status["usage"]["used_today"] == 1

    def test_yesterdays_messages_do_not_count_against_today(
        self, client: TestClient, db: Session
    ) -> None:
        stock_the_feed(db, ["Nvidia signs a chip licensing agreement"])
        use()
        tokens = signup(client, "rollover@example.com")
        headers = auth_headers(tokens)
        for _ in range(5):
            client.post("/ai/ask", json={"question": MATCHING_QUESTION}, headers=headers)

        use(NOW + timedelta(days=1))
        after_midnight = client.get("/ai/status", headers=headers).json()

        assert after_midnight["usage"]["used_today"] == 0

    def test_a_model_outage_is_a_503_not_a_500(self, client: TestClient, db: Session) -> None:
        """It is their outage, not our bug, and it is worth retrying."""
        stock_the_feed(db, ["Nvidia signs a chip licensing agreement"])

        class Broken(FakeLLM):
            def complete(self, system, user, *, max_tokens=512, json_object=False):
                raise LLMError("broken", "model is down")

        use(client_impl=Broken())
        tokens = signup(client, "outage@example.com")

        response = client.post(
            "/ai/ask", json={"question": MATCHING_QUESTION}, headers=auth_headers(tokens)
        )

        assert response.status_code == 503

    @pytest.mark.parametrize("question", ["", "ab", "x" * 2001])
    def test_a_malformed_question_is_rejected_before_it_costs_anything(
        self, client: TestClient, question: str
    ) -> None:
        use()
        tokens = signup(client, f"bad{len(question)}@example.com")

        response = client.post("/ai/ask", json={"question": question}, headers=auth_headers(tokens))

        assert response.status_code == 422
