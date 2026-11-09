/**
 * Pure helpers for the live dashboard. No React, no fetch, no implicit clock -
 * so every rule here is unit-tested.
 */

import type { Dashboard, SignalBandCode } from "@/lib/types";

export const EXCHANGE_TZ = "America/New_York";

/** EventSource failures in a row before giving up on streaming and polling instead. */
export const MAX_STREAM_ERRORS = 3;

export type Transport = "connecting" | "streaming" | "polling";

/** "12:03:14 PM ET". Always exchange time, whatever the viewer's timezone. */
export function formatExchangeTime(iso: string, withSeconds = true): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const time = new Intl.DateTimeFormat("en-US", {
    timeZone: EXCHANGE_TZ,
    hour: "numeric",
    minute: "2-digit",
    ...(withSeconds ? { second: "2-digit" } : {}),
  }).format(date);
  return `${time} ET`;
}

/**
 * "Fri, Sep 11" from a session date such as "2026-09-11".
 *
 * A bare date parses as UTC midnight, which is the previous evening in New
 * York, so it is formatted in UTC to keep the calendar day it names.
 */
export function formatSessionDay(sessionDate: string): string {
  const date = new Date(`${sessionDate}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return sessionDate;
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "UTC",
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(date);
}

/** "Mon 9:30 AM ET" */
export function formatNextOpen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: EXCHANGE_TZ,
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
  return `${parts} ET`;
}

/** The one-line market state under the dashboard title. */
export function marketHeadline(dashboard: Dashboard): string {
  const { market } = dashboard;
  if (market.is_open) {
    const close = market.next_close ? ` · closes ${formatExchangeTime(market.next_close, false)}` : "";
    return `Market open${close}`;
  }
  const reason = market.reason ?? "Market closed";
  return `${reason} · showing ${formatSessionDay(market.last_completed_session)} close · opens ${formatNextOpen(market.next_open)}`;
}

/** The `source` the API stamps on every simulated row. Mirrors SIMULATED_SOURCE in Python. */
export const SIMULATED_SOURCE = "simulated";

/**
 * Which parts of the dashboard are simulated.
 *
 * Prices and signals can differ: with a real quote key but no daily-bar key,
 * prices are live while the history behind each signal is still the
 * simulator's. Saying "these prices are not real" when they are would train
 * the reader to ignore the notice, so the notice names what is actually fake.
 */
export function simulatedParts(dashboard: Dashboard): { prices: boolean; signals: boolean } {
  return {
    prices: dashboard.rows.some((row) => row.source === SIMULATED_SOURCE),
    signals: dashboard.rows.some((row) => row.signal?.source === SIMULATED_SOURCE),
  };
}

/**
 * The server's clock right now, estimated from the last payload.
 *
 * "Updated 2 minutes ago" must be measured on the server's clock, not the
 * browser's (a laptop clock can be minutes off). The payload carries
 * server_time; the browser clock is only used to measure time *elapsed* since
 * that payload arrived, which is immune to the browser's clock being wrong.
 */
export function serverNow(serverTime: string, receivedAtMs: number, nowMs: number): Date {
  const server = Date.parse(serverTime);
  if (Number.isNaN(server)) return new Date(nowMs);
  return new Date(server + Math.max(0, nowMs - receivedAtMs));
}

/** What to do after a stream error, given how many have happened in a row. */
export function streamErrorAction(consecutiveErrors: number): "retry" | "fallback" {
  return consecutiveErrors >= MAX_STREAM_ERRORS ? "fallback" : "retry";
}

export const BAND_LABEL: Record<SignalBandCode, string> = {
  strong_bearish: "Strong bearish",
  bearish: "Bearish",
  neutral: "Neutral",
  bullish: "Bullish",
  strong_bullish: "Strong bullish",
};

export function signedNumber(value: number, digits = 1): string {
  const fixed = value.toFixed(digits);
  return value > 0 ? `+${fixed}` : fixed;
}
