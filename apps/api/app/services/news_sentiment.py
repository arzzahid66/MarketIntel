"""News sentiment: the LLM half of the signal.

The build plan's rule is that the signal itself is deterministic and never "an
LLM saying bullish". This module keeps to that line. A model is used for the one
job a formula does badly - reading a headline and judging whether it is good or
bad for the business - and its output enters the signal as a single bounded
number in the `news_sentiment_7d` term, carrying 0.15 of the score. The maths
around it stays in `signals.py`, where it is reproducible.

Two decisions worth knowing:

  * **Scoring happens once per article, at ingest, and is stored.** Never per
    viewer and never per refresh, or LLM cost scales with traffic instead of
    with news volume.
  * **A score is stored with its model and prompt version.** A signal a customer
    saw must be reproducible, and changing this prompt changes the scores it
    produces. Bump PROMPT_VERSION on any wording change, and FORMULA_VERSION in
    `signals.py` when sentiment first goes live, so old snapshots stay readable.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.logging import get_logger
from app.llm.base import LLMClient, LLMRefused

log = get_logger("services.news_sentiment")

#: Bump on any wording change below. Stored with every score.
#: 2 - one call now returns category and summary alongside sentiment.
PROMPT_VERSION = 2

#: The signal's news term looks back this far.
LOOKBACK_DAYS = 7
#: A three-day half-life: a week-old headline still counts, at about a fifth of
#: a headline from this morning. The plan says "weight recent news more heavily"
#: without giving a curve; this is the assumption, and it is one constant.
HALF_LIFE_DAYS = 3.0

#: How much each materiality band counts toward the aggregate. Routine coverage
#: is not ignored, just quiet - a wall of filler cannot outvote one lawsuit.
MATERIALITY_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.25}

SYSTEM_PROMPT = """\
You read one financial news item and report on it: how it affects a single \
company's future earnings and business, which category it belongs to, and what \
it says in one line. You are one input to a larger quantitative signal, not a \
recommendation engine.

Return ONLY valid JSON, no other text:
{"sentiment": <number between -1.0 and 1.0>,
 "label": "positive" | "negative" | "neutral",
 "materiality": "high" | "medium" | "low",
 "rationale": "<one short sentence>",
 "category": "<one key from the list given, or null if none fit>",
 "summary": "<one neutral sentence, under 200 characters>"}

The summary is shown to readers in place of the publisher's own, so write it \
plainly and claim nothing the item does not say. Pick the category whose \
description fits best; do not invent a key that was not listed.

Scoring:
- -1.0 is severely damaging (fraud, bankruptcy risk, collapsing revenue), +1.0 \
is transformatively good, 0.0 is neutral or irrelevant.
- Judge the effect on the business, not whether the stock is cheap or expensive.
- materiality is "high" for events that change the earnings outlook (earnings, \
guidance, lawsuits, regulation, leadership changes, major deals, recalls), \
"medium" for solid reporting with modest impact, "low" for routine coverage, \
opinion, or speculation without substance.

Rules you must not break:
- A price movement is not news. "Shares fall 5%" scores 0.0 unless the item \
gives a business cause. The signal already measures price separately, and \
scoring price here would count the same fact twice.
- Use only the headline and summary provided. Do not use outside knowledge of \
what happened afterwards, and never invent facts, figures or events.
- If the item is not about this company, score 0.0 with materiality "low".
- Never output a recommendation to buy, sell or hold.\
"""


@dataclass(frozen=True)
class Article:
    """One news item. Mirrors the fields rule 4 requires on every ingested row."""

    headline: str
    summary: str | None
    url: str
    publisher: str
    published_at: datetime


@dataclass(frozen=True)
class ArticleSentiment:
    score: float
    label: str
    materiality: str
    rationale: str
    model: str
    prompt_version: int


@dataclass(frozen=True)
class ScoredArticle:
    article: Article
    sentiment: ArticleSentiment


@dataclass(frozen=True)
class ArticleAssessment:
    """Everything one LLM call produces for one article-and-company pair.

    Category and summary describe the article and are the same whichever company
    is being scored; sentiment is per company. Both come back together because
    one call costs half what two cost, and the article text is the expensive
    part of the prompt either way.
    """

    sentiment: ArticleSentiment
    category_key: str | None
    ai_summary: str


@dataclass(frozen=True)
class CategoryChoice:
    key: str
    description: str


def build_user_prompt(
    article: Article,
    company: str,
    symbol: str,
    categories: Sequence[CategoryChoice] = (),
) -> str:
    summary = (article.summary or "").strip()
    lines = [
        f"Company: {company} ({symbol})",
        f"Publisher: {article.publisher}",
        f"Published: {article.published_at.date().isoformat()}",
        f"Headline: {article.headline.strip()}",
        f"Summary: {summary or '(none provided)'}",
    ]
    if categories:
        lines.append("")
        lines.append("Categories to choose from:")
        lines += [f"- {c.key}: {c.description}" for c in categories]
    return "\n".join(lines)


def _extract_json(text: str) -> dict:
    """Pull the JSON object out of a model reply.

    Models wrap JSON in code fences or a sentence of preamble often enough that
    failing on it would throw away good scores, so the object is located rather
    than assumed to be the whole reply.
    """
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise LLMRefused("parser", "no JSON object in reply")
    try:
        data = json.loads(match.group(0))
    except ValueError as exc:
        raise LLMRefused("parser", "reply was not valid JSON") from exc
    if not isinstance(data, dict):
        raise LLMRefused("parser", "reply JSON was not an object")
    return data


def parse_sentiment(text: str, model: str) -> ArticleSentiment:
    """Validate a model reply into a bounded score.

    Strict where it matters and forgiving where it does not: `sentiment` must be
    a number or the score is refused, while a missing or unknown `materiality`
    falls back to "low", which quietens the article rather than dropping it.
    """
    data = _extract_json(text)

    raw = data.get("sentiment")
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise LLMRefused("parser", f"sentiment was {type(raw).__name__}, not a number")
    score = max(-1.0, min(1.0, float(raw)))

    materiality = str(data.get("materiality", "")).lower()
    if materiality not in MATERIALITY_WEIGHT:
        materiality = "low"

    label = str(data.get("label", "")).lower()
    if label not in ("positive", "negative", "neutral"):
        # Derivable from the score, so an odd label is not worth losing a score over.
        label = "positive" if score > 0.15 else "negative" if score < -0.15 else "neutral"

    rationale = str(data.get("rationale", "")).strip()[:300]
    return ArticleSentiment(
        score=round(score, 4),
        label=label,
        materiality=materiality,
        rationale=rationale,
        model=model,
        prompt_version=PROMPT_VERSION,
    )


def parse_assessment(text: str, model: str, allowed: Sequence[str] = ()) -> ArticleAssessment:
    """Validate a reply into sentiment plus category and summary.

    An unrecognised category becomes None rather than being stored: a key the
    taxonomy does not contain would show as an empty filter in the UI, and
    "uncategorised" is an honest answer.
    """
    data = _extract_json(text)
    sentiment = parse_sentiment(text, model)

    category = data.get("category")
    key = str(category).strip().lower() if category else ""
    if allowed and key not in {a.lower() for a in allowed}:
        key = ""

    return ArticleAssessment(
        sentiment=sentiment,
        category_key=key or None,
        ai_summary=str(data.get("summary", "")).strip()[:400],
    )


def assess_article(
    client: LLMClient,
    article: Article,
    company: str,
    symbol: str,
    categories: Sequence[CategoryChoice] = (),
) -> ArticleAssessment:
    """One call: sentiment, category and summary. Raises LLMError/LLMRefused."""
    prompt = build_user_prompt(article, company, symbol, categories)
    response = client.complete(SYSTEM_PROMPT, prompt, json_object=True)
    return parse_assessment(response.text, response.model, [c.key for c in categories])


def score_article(
    client: LLMClient, article: Article, company: str, symbol: str
) -> ArticleSentiment:
    """Sentiment only, for callers that do not need the category."""
    return assess_article(client, article, company, symbol).sentiment


def aggregate_7d(
    scored: Sequence[ScoredArticle],
    now: datetime,
    lookback_days: int = LOOKBACK_DAYS,
    half_life_days: float = HALF_LIFE_DAYS,
) -> float | None:
    """Combine scored articles into the signal's `news_sentiment_7d` term.

    Returns None when there is nothing in the window. That is deliberate: no news
    is not the same as balanced news, and `compute_signal` already distinguishes
    them - None marks the component unavailable instead of silently voting 0.
    """
    cutoff = now - timedelta(days=lookback_days)
    total = weight_sum = 0.0

    for item in scored:
        published = item.article.published_at
        if published < cutoff:
            continue
        # Clock skew or a publisher dating ahead: treat as brand new, never negative age.
        age_days = max(0.0, (now - published).total_seconds() / 86400.0)
        recency = 0.5 ** (age_days / half_life_days)
        weight = MATERIALITY_WEIGHT[item.sentiment.materiality] * recency
        total += item.sentiment.score * weight
        weight_sum += weight

    if weight_sum == 0.0:
        return None
    return max(-1.0, min(1.0, round(total / weight_sum, 4)))
