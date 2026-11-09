/**
 * Formatting helpers.
 *
 * "Last updated 2 minutes ago" is computed from a server timestamp, never from
 * the browser clock (Phase 2 exit criterion). These functions therefore always
 * take an explicit `now` so they are pure and testable.
 */

import { UNLIMITED } from "@/lib/types";

export function formatPrice(value: number | null | undefined, currency = "USD"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export type Direction = "bull" | "bear" | "flat";

export function directionOf(value: number | null | undefined): Direction {
  if (value === null || value === undefined || Number.isNaN(value) || value === 0) return "flat";
  return value > 0 ? "bull" : "bear";
}

/** Whole-unit price from cents, e.g. 1900 -> "$19". Free renders as "Free". */
export function formatMonthlyPrice(cents: number, currency = "USD"): string {
  if (cents === 0) return "Free";
  const amount = cents / 100;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: amount % 1 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

/**
 * Relative time from a server timestamp.
 *
 * Deliberately coarse: to the second under a minute, then whole minutes. There
 * is no point implying precision the data does not have.
 */
export function formatRelativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "unknown";

  const seconds = Math.floor((now.getTime() - then.getTime()) / 1000);
  if (seconds < 0) return "just now";
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds} seconds ago`;

  const minutes = Math.floor(seconds / 60);
  if (minutes === 1) return "1 minute ago";
  if (minutes < 60) return `${minutes} minutes ago`;

  const hours = Math.floor(minutes / 60);
  if (hours === 1) return "1 hour ago";
  if (hours < 24) return `${hours} hours ago`;

  const days = Math.floor(hours / 24);
  return days === 1 ? "1 day ago" : `${days} days ago`;
}

/** Renders a plan limit for humans. -1 is "Unlimited", 0 is a plain dash. */
export function formatLimit(value: number): string {
  if (value === UNLIMITED) return "Unlimited";
  if (value === 0) return "—";
  return String(value);
}

export function formatInterval(seconds: number): string {
  if (seconds < 60) return `${seconds} sec`;
  const minutes = Math.round(seconds / 60);
  return minutes === 1 ? "1 min" : `${minutes} min`;
}
