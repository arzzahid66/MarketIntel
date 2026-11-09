"use client";

/**
 * The news & social feed.
 *
 * A list rather than a table: the rows are headlines of different lengths, not
 * comparable figures, and section 6 reserves tables for things the eye scans
 * down a column. Colour still means direction and nothing else - a category is
 * plain text, and only the sentiment chip is tinted.
 *
 * Every row shows its publisher and links to the original. That is rule 4
 * reaching the reader: an item we cannot attribute has no business being here.
 */

import { useCallback, useState } from "react";

import { formatExchangeTime } from "@/lib/market";
import type { Feed, FeedItem, FeedTicker } from "@/lib/types";

const ALL = "all";

function toneFor(sentiment: number | null): string {
  if (sentiment === null) return "border-line bg-bg text-muted";
  if (sentiment <= -0.15) return "border-bear/30 bg-bear-wash text-bear";
  if (sentiment >= 0.15) return "border-bull/30 bg-bull-wash text-bull";
  return "border-line bg-bg text-muted";
}

function TickerChip({ ticker }: { ticker: FeedTicker }) {
  const value = ticker.sentiment;
  return (
    <span
      className={`inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-[var(--radius-ui)] border px-2 text-small font-medium ${toneFor(value)}`}
      title={ticker.rationale ?? undefined}
    >
      <span className="font-mono">{ticker.symbol}</span>
      {value !== null && (
        <span className="tnum opacity-70">
          {value > 0 ? "+" : ""}
          {value.toFixed(2)}
        </span>
      )}
    </span>
  );
}

function Row({ item }: { item: FeedItem }) {
  return (
    <article className="border-b border-line px-4 py-3 last:border-b-0">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-small text-muted">
        <span>{item.publisher}</span>
        <span aria-hidden="true">·</span>
        <time dateTime={item.published_at}>{formatExchangeTime(item.published_at, false)}</time>
        {item.category && (
          <>
            <span aria-hidden="true">·</span>
            <span>{item.category.label}</span>
          </>
        )}
      </div>

      <h3 className="mt-1 text-body font-medium leading-snug">
        <a
          href={item.source_url}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="text-ink hover:text-action"
        >
          {item.title}
        </a>
      </h3>

      {item.summary && (
        <p className="mt-1 text-small text-muted">
          {item.summary}
          {item.summary_is_ai && (
            // Said plainly: a summary the reader might quote should not be
            // mistaken for the publisher's own words.
            <span className="ml-1.5 opacity-70">(AI summary)</span>
          )}
        </p>
      )}

      {item.tickers.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {item.tickers.map((t) => (
            <TickerChip key={t.symbol} ticker={t} />
          ))}
        </div>
      )}
    </article>
  );
}

export function FeedPanel({ initial }: { initial: Feed }) {
  // Derived, not mirrored: `initial` is the server render and does not change
  // while the page is open, so copying it into state with an effect would add a
  // cascading render for nothing - which is what the react-hooks lint rule
  // objects to. A filtered fetch simply takes precedence until it is cleared.
  const [filtered, setFiltered] = useState<Feed | null>(null);
  const [active, setActive] = useState(ALL);
  const [loading, setLoading] = useState(false);
  const feed = filtered ?? initial;

  const select = useCallback(async (key: string) => {
    setActive(key);
    if (key === ALL) {
      setFiltered(null);
      return;
    }
    setLoading(true);
    try {
      const response = await fetch(`/api/feed?category=${encodeURIComponent(key)}`, {
        cache: "no-store",
      });
      if (response.ok) setFiltered((await response.json()) as Feed);
    } catch {
      // Keep whatever is on screen; the reader can pick another filter.
    } finally {
      setLoading(false);
    }
  }, []);

  const tabs = [{ key: ALL, label: "All" }, ...feed.categories];

  return (
    <section className="border border-line bg-surface rounded-[var(--radius-ui)]">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <h2 className="text-lg font-semibold tracking-tight">News &amp; social feed</h2>
        <nav className="flex flex-wrap gap-1" aria-label="Filter by category">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => select(tab.key)}
              aria-pressed={active === tab.key}
              className={`h-7 rounded-[var(--radius-ui)] border px-2 text-small transition-colors ${
                active === tab.key
                  ? "border-line bg-bg font-medium text-ink"
                  : "border-transparent text-muted hover:text-ink"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>

      <div className={loading ? "opacity-60 transition-opacity" : "transition-opacity"}>
        {feed.items.length === 0 ? (
          <p className="px-4 py-8 text-center text-small text-muted">
            Nothing here yet. Headlines appear as they are published and scored.
          </p>
        ) : (
          feed.items.map((item) => <Row key={item.id} item={item} />)
        )}
      </div>
    </section>
  );
}
