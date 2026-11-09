"use client";

/**
 * "Updated 12:03:14 PM ET · 2 min ago" plus a small refresh icon button.
 *
 * Section 6: a quiet muted line, not a pill, not a badge, not green.
 *
 * `updatedAt` is when *our servers* fetched the data shown, and the relative age
 * is measured on the server's clock (see serverNow), so a viewer whose laptop
 * clock is ten minutes fast still sees the truth.
 */

import { useEffect, useState } from "react";

import { formatRelativeTime } from "@/lib/format";
import { formatExchangeTime, serverNow } from "@/lib/market";
import type { Transport } from "@/lib/market";

const TICK_MS = 15_000;

export function LastUpdated({
  updatedAt,
  serverTime,
  receivedAt,
  onRefresh,
  refreshing = false,
  transport,
}: {
  updatedAt: string | null;
  serverTime: string;
  receivedAt: number;
  onRefresh: () => void;
  refreshing?: boolean;
  transport: Transport;
}) {
  // The browser clock is sampled in state, from an interval callback, so render
  // stays pure. It only ever measures elapsed time since the payload arrived.
  const [browserNow, setBrowserNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setBrowserNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, []);

  const now = serverNow(serverTime, receivedAt, browserNow);
  const label = updatedAt
    ? `Updated ${formatExchangeTime(updatedAt)} · ${formatRelativeTime(updatedAt, now)}`
    : "Not updated yet";
  const transportLabel = transport === "polling" ? " · auto-refresh" : "";

  return (
    <div className="flex items-center gap-2 text-small text-muted">
      {/* Clock-derived text: server and first client render can differ by a
          second, which is not a hydration bug worth shouting about. */}
      <span suppressHydrationWarning>
        {label}
        {transportLabel}
      </span>
      <button
        type="button"
        onClick={onRefresh}
        disabled={refreshing}
        aria-label="Refresh prices"
        title="Refresh"
        className="inline-flex h-6 w-6 items-center justify-center rounded-[var(--radius-ui)] text-muted hover:text-ink disabled:opacity-50"
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          className={refreshing ? "animate-spin" : undefined}
        >
          <path d="M21 12a9 9 0 1 1-3-6.7" />
          <path d="M21 3v6h-6" />
        </svg>
      </button>
    </div>
  );
}
