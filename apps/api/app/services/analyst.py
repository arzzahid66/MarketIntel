"""The AI analyst: retrieval over the feed, then a grounded answer.

This is the one surface where an LLM speaks to the customer in its own words, so
the constraints are tighter than anywhere else in the codebase:

  * **It answers only from retrieved articles.** No outside knowledge, no
    recalled facts. If the feed does not cover the question, the honest answer
    is that it does not - a plausible answer from memory about a real company's
    finances is the worst thing this product could emit.
  * **Every claim carries a citation**, and the citations are the articles we
    actually retrieved. Rule 4 exists for this moment: the reader can click
    through to the publisher and check.
  * **It never recommends a trade.** Not "buy", not "sell", not "I would".
    Describing what the news says is the product; telling someone what to do
    with their money is advice, and we are not licensed to give it.

Retrieval is cosine distance over `feed_items.embedding` (pgvector `<=>`), which
is why the HNSW index in migration 0004 uses `vector_cosine_ops` - a mismatched
operator class would silently fall back to a full scan.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.llm.base import LLMClient, LLMError
from app.models.analyst import AiMessage
from app.models.feed import FeedItem
from app.models.ticker import Ticker

log = get_logger("services.analyst")

#: Bump on any wording change to SYSTEM_PROMPT. Stored with every answer.
PROMPT_VERSION = 1

#: How many articles the model is shown. Enough for a rounded answer, few enough
#: that the prompt stays cheap and the model cannot drown the relevant one.
RETRIEVE_TOP_K = 8
#: Articles older than this are not retrieved: a question about a company is
#: almost always about now, and stale context reads as the model being wrong.
RETRIEVE_WINDOW_DAYS = 30
#: Cosine distance above this is not really about the question. pgvector's `<=>`
#: returns 0 (identical) to 2 (opposite); 0.6 keeps loosely-related articles out.
MAX_DISTANCE = 0.6

SYSTEM_PROMPT = """\
You are a market news analyst for a subscription dashboard. You answer questions \
using ONLY the numbered articles provided below. You are not a financial adviser.

Rules you must not break:
- Use only the provided articles. If they do not answer the question, say so \
plainly and stop. Never fill a gap from memory, and never invent a figure, date, \
company or event.
- Cite with the article's number in square brackets, like [2], immediately after \
each claim that comes from it. Every factual sentence needs a citation.
- Never recommend buying, selling or holding anything, and never say what you \
would do. Describe what the articles report and what it bears on. If asked for a \
recommendation, explain that you report what the news says and cannot give \
financial advice.
- Do not predict prices or give target prices, even if an article does. You may \
report that an analyst made a prediction, attributed and cited.
- Be brief: a short paragraph, or a few sentences. Say what the articles support \
and nothing more.
- If the articles disagree, say so and cite both.\
"""

NO_CONTEXT_ANSWER = (
    "I do not have any recent articles about that in the feed, so I cannot answer "
    "it. The feed covers the Big 7 companies over roughly the last month."
)


@dataclass(frozen=True)
class Citation:
    number: int
    feed_item_id: str
    title: str
    publisher: str
    source_url: str
    published_at: datetime

    def to_json(self) -> dict:
        return {
            "number": self.number,
            "feed_item_id": self.feed_item_id,
            "title": self.title,
            "publisher": self.publisher,
            "source_url": self.source_url,
            "published_at": self.published_at.isoformat(),
        }


@dataclass(frozen=True)
class Answer:
    text: str
    citations: list[Citation]
    model: str
    prompt_version: int
    retrieved: int


def retrieve(
    db: Session,
    client: LLMClient,
    question: str,
    now: datetime,
    top_k: int = RETRIEVE_TOP_K,
    window_days: int = RETRIEVE_WINDOW_DAYS,
    max_distance: float = MAX_DISTANCE,
    symbol: str | None = None,
) -> list[FeedItem]:
    """The articles most similar to the question, nearest first."""
    vector = client.embed([question])[0]
    cutoff = now - timedelta(days=window_days)

    distance = FeedItem.embedding.cosine_distance(vector)
    statement = (
        select(FeedItem, distance.label("distance"))
        .where(
            FeedItem.embedding.is_not(None),
            FeedItem.published_at >= cutoff,
            distance < max_distance,
        )
        .order_by(distance)
        .limit(top_k)
    )
    if symbol:
        statement = statement.join(FeedItem.tickers).join(Ticker).where(Ticker.symbol == symbol)

    return [row[0] for row in db.execute(statement).unique().all()]


def build_context(items: list[FeedItem]) -> tuple[str, list[Citation]]:
    """Number the articles for the prompt and build the matching citations.

    The numbering is the contract between the two: the model cites [3], and [3]
    resolves to the third article here. Any change to one must change the other.
    """
    blocks: list[str] = []
    citations: list[Citation] = []

    for number, item in enumerate(items, start=1):
        summary = item.ai_summary or item.summary or ""
        tickers = ", ".join(sorted({link.ticker.symbol for link in item.tickers}))
        blocks.append(
            f"[{number}] {item.title}\n"
            f"Publisher: {item.publisher}\n"
            f"Published: {item.published_at.date().isoformat()}\n"
            f"Companies: {tickers or 'unspecified'}\n"
            f"{summary}"
        )
        citations.append(
            Citation(
                number=number,
                feed_item_id=str(item.id),
                title=item.title,
                publisher=item.publisher,
                source_url=item.source_url,
                published_at=item.published_at,
            )
        )

    return "\n\n".join(blocks), citations


def ask(
    db: Session,
    client: LLMClient,
    user_id: uuid.UUID,
    question: str,
    now: datetime,
    symbol: str | None = None,
) -> Answer:
    """Answer one question from the feed, and record it.

    The record is written whether or not the model had context, because the row
    is both the audit trail and the meter - an answer that cost a request must
    count against the quota even when the answer was "I don't know".
    """
    items = retrieve(db, client, question, now, symbol=symbol)

    if not items:
        answer = Answer(NO_CONTEXT_ANSWER, [], client.model, PROMPT_VERSION, 0)
    else:
        context, citations = build_context(items)
        user_prompt = f"Articles:\n\n{context}\n\nQuestion: {question.strip()}"
        try:
            response = client.complete(SYSTEM_PROMPT, user_prompt, max_tokens=700)
        except LLMError:
            log.exception("analyst_failed")
            raise
        answer = Answer(
            text=response.text.strip(),
            # Only the citations the model actually used, so the reader is not
            # shown a list of sources the answer never drew on.
            citations=[c for c in citations if f"[{c.number}]" in response.text],
            model=response.model,
            prompt_version=PROMPT_VERSION,
            retrieved=len(items),
        )

    db.add(
        AiMessage(
            # Stamped from the injected clock, not the database's `now()`. The
            # quota window is computed from this same clock, and two clocks
            # deciding one question is how an allowance silently mis-counts.
            created_at=now,
            user_id=user_id,
            question=question.strip()[:2000],
            answer=answer.text,
            citations_json=[c.to_json() for c in answer.citations],
            model=answer.model,
            prompt_version=answer.prompt_version,
            retrieved=answer.retrieved,
        )
    )
    db.commit()
    return answer
