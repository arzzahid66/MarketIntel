import { describe, expect, it } from "vitest";

import {
  directionOf,
  formatInterval,
  formatLimit,
  formatMonthlyPrice,
  formatPercent,
  formatPrice,
  formatRelativeTime,
} from "@/lib/format";
import { UNLIMITED } from "@/lib/types";

describe("formatPrice", () => {
  it("formats to two decimals so a column aligns", () => {
    expect(formatPrice(1234.5)).toBe("$1,234.50");
  });

  it("renders an em dash rather than 0 or NaN when there is no data", () => {
    expect(formatPrice(null)).toBe("—");
    expect(formatPrice(undefined)).toBe("—");
    expect(formatPrice(Number.NaN)).toBe("—");
  });
});

describe("formatPercent", () => {
  it("always shows the sign for a gain", () => {
    expect(formatPercent(1.5)).toBe("+1.50%");
    expect(formatPercent(-1.5)).toBe("-1.50%");
    expect(formatPercent(0)).toBe("0.00%");
  });
});

describe("directionOf", () => {
  it("treats zero and missing data as flat, never as a move", () => {
    expect(directionOf(0)).toBe("flat");
    expect(directionOf(null)).toBe("flat");
    expect(directionOf(0.1)).toBe("bull");
    expect(directionOf(-0.1)).toBe("bear");
  });
});

describe("formatMonthlyPrice", () => {
  it("says Free rather than $0.00", () => {
    expect(formatMonthlyPrice(0)).toBe("Free");
  });

  it("drops cents for whole amounts", () => {
    expect(formatMonthlyPrice(1900)).toBe("$19");
    expect(formatMonthlyPrice(1950)).toBe("$19.50");
  });
});

describe("formatLimit", () => {
  it("renders the unlimited sentinel as a word, not -1", () => {
    expect(formatLimit(UNLIMITED)).toBe("Unlimited");
    expect(formatLimit(0)).toBe("—");
    expect(formatLimit(15)).toBe("15");
  });
});

describe("formatInterval", () => {
  it("switches to minutes above a minute", () => {
    expect(formatInterval(15)).toBe("15 sec");
    expect(formatInterval(60)).toBe("1 min");
    expect(formatInterval(300)).toBe("5 min");
  });
});

describe("formatRelativeTime", () => {
  const now = new Date("2026-01-15T12:00:00Z");

  it("is computed against a supplied clock, never the browser's own", () => {
    expect(formatRelativeTime("2026-01-15T11:58:00Z", now)).toBe("2 minutes ago");
    expect(formatRelativeTime("2026-01-15T11:59:55Z", now)).toBe("just now");
    expect(formatRelativeTime("2026-01-15T11:00:00Z", now)).toBe("1 hour ago");
    expect(formatRelativeTime("2026-01-13T12:00:00Z", now)).toBe("2 days ago");
  });

  it("never shows a negative age when a server clock runs slightly ahead", () => {
    expect(formatRelativeTime("2026-01-15T12:00:30Z", now)).toBe("just now");
  });

  it("degrades to a word instead of throwing on a bad timestamp", () => {
    expect(formatRelativeTime("not-a-date", now)).toBe("unknown");
  });
});
