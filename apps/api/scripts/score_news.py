"""Score news headlines with the configured LLM, from the command line.

The news scorer is not wired into any page or worker job yet (that is the Phase 3
ingest layer), so this is how you exercise it by hand - to check a key works, to
see what the model does with a particular headline, or to compare the real model
against the stub.

    cd apps/api

    # Real headlines for a ticker, straight from Finnhub
    ../../.venv/Scripts/python.exe scripts/score_news.py AAPL

    # One headline of your own
    ../../.venv/Scripts/python.exe scripts/score_news.py TSLA \
        --headline "Tesla recalls 400,000 vehicles over steering fault"

    # Force the offline stub, to see the difference without spending anything
    ../../.venv/Scripts/python.exe scripts/score_news.py AAPL --stub

Every call costs money when LLM_PROVIDER resolves to openai, so --limit defaults
to 5 rather than scoring everything the feed returns.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.llm import build_llm_client
from app.llm.base import LLMError
from app.llm.fake import FakeLLM
from app.services.news_sentiment import (
    LOOKBACK_DAYS,
    Article,
    ScoredArticle,
    aggregate_7d,
    score_article,
)

#: Symbol -> the company name the prompt is given. The real pipeline will read
#: this from the tickers table; here it only needs the Big 7.
COMPANIES = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "GOOGL": "Alphabet Inc.",
    "AMZN": "Amazon.com Inc.",
    "NVDA": "NVIDIA Corporation",
    "META": "Meta Platforms Inc.",
    "TSLA": "Tesla Inc.",
}


def fetch_headlines(symbol: str, days: int, limit: int) -> list[Article]:
    """Real company news from Finnhub. Works on the free tier."""
    key = settings.finnhub_api_key.get_secret_value()
    if not key:
        sys.exit("FINNHUB_API_KEY is not set, so there are no headlines to score.")

    today = datetime.now(UTC).date()
    url = (
        f"https://finnhub.io/api/v1/company-news?symbol={symbol}"
        f"&from={today - timedelta(days=days)}&to={today}"
    )
    request = urllib.request.Request(url, headers={"X-Finnhub-Token": key})
    with urllib.request.urlopen(request, timeout=20) as response:
        items = json.load(response)

    return [
        Article(
            headline=item["headline"],
            summary=item.get("summary") or None,
            url=item["url"],
            publisher=item.get("source") or "unknown",
            published_at=datetime.fromtimestamp(item["datetime"], UTC),
        )
        for item in items[:limit]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol", nargs="?", default="AAPL", help="ticker (default: AAPL)")
    parser.add_argument("--headline", help="score this one headline instead of fetching")
    parser.add_argument("--summary", default=None, help="optional summary for --headline")
    parser.add_argument("--limit", type=int, default=5, help="headlines to score (default: 5)")
    parser.add_argument("--days", type=int, default=LOOKBACK_DAYS, help="look back this far")
    parser.add_argument("--stub", action="store_true", help="force the offline keyword scorer")
    args = parser.parse_args()

    symbol = args.symbol.upper()
    company = COMPANIES.get(symbol, symbol)
    now = datetime.now(UTC)

    client = FakeLLM() if args.stub else build_llm_client(settings)
    print(f"client   : {client.name}  model={client.model}  simulated={client.is_simulated}")
    if client.is_simulated and not args.stub:
        print("           (no OPENAI_API_KEY, so this is the keyword stub, not a real model)")
    print(f"scoring  : {company} ({symbol})\n")

    if args.headline:
        articles = [
            Article(
                headline=args.headline,
                summary=args.summary,
                url="https://example.invalid/manual",
                publisher="manual",
                published_at=now,
            )
        ]
    else:
        articles = fetch_headlines(symbol, args.days, args.limit)
        if not articles:
            sys.exit(f"Finnhub returned no headlines for {symbol} in the last {args.days} days.")

    scored: list[ScoredArticle] = []
    for article in articles:
        try:
            sentiment = score_article(client, article, company, symbol)
        except LLMError as exc:
            # One bad article must never stop the run; the real ingest job skips too.
            print(f"  SKIPPED  {article.headline[:60]}\n           {exc}")
            continue
        scored.append(ScoredArticle(article, sentiment))
        age = (now - article.published_at).total_seconds() / 86400.0
        print(f"{sentiment.score:+.2f}  {sentiment.label:8} {sentiment.materiality:6} "
              f"{age:4.1f}d  {article.headline[:58]}")
        print(f"       {sentiment.rationale}")
        print(f"       {article.publisher} - {article.url[:80]}")

    if not scored:
        sys.exit("\nNothing scored.")

    aggregate = aggregate_7d(scored, now)
    print(f"\nscored {len(scored)} of {len(articles)} article(s)")
    print(f"news_sentiment_7d = {aggregate}")
    print(
        "This is the number that enters the signal at 0.15 weight. "
        f"It moves the score by {0.15 * 100 * (aggregate or 0):+.1f} points."
    )


if __name__ == "__main__":
    main()
