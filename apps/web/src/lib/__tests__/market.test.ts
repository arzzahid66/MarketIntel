import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { bandForScore } from "@/components/ui/SignalBadge";
import {
  MAX_STREAM_ERRORS,
  formatExchangeTime,
  formatNextOpen,
  formatSessionDay,
  marketHeadline,
  serverNow,
  signedNumber,
  simulatedParts,
  streamErrorAction,
} from "@/lib/market";
import type { Dashboard, MarketRow, Signal } from "@/lib/types";

describe("signal bands", () => {
  it("agree with the API's copy of the thresholds (shared/signal_bands.json)", () => {
    const url = new URL("../../../../../shared/signal_bands.json", import.meta.url);
    const { cases } = JSON.parse(readFileSync(url, "utf-8")) as {
      cases: Array<{ score: number; band: string }>;
    };
    expect(cases.length).toBeGreaterThan(0);
    for (const { score, band } of cases) {
      expect(bandForScore(score), `score ${score}`).toBe(band);
    }
  });
});

describe("exchange time formatting", () => {
  it("shows New York time to the second, whatever the viewer's timezone", () => {
    expect(formatExchangeTime("2026-09-14T16:03:14Z")).toBe("12:03:14 PM ET"); // EDT
    expect(formatExchangeTime("2026-01-15T16:03:14Z")).toBe("11:03:14 AM ET"); // EST
  });

  it("keeps the calendar day of a session date instead of shifting it into yesterday", () => {
    expect(formatSessionDay("2026-09-11")).toBe("Fri, Sep 11");
  });

  it("formats the next open", () => {
    expect(formatNextOpen("2026-09-14T13:30:00Z")).toBe("Mon 9:30 AM ET");
  });
});

function dashboard(market: Partial<Dashboard["market"]>): Dashboard {
  return {
    server_time: "2026-09-14T16:00:00Z",
    last_updated_at: "2026-09-14T16:00:00Z",
    data_status: "live",
    is_simulated: false,
    provider: "finnhub",
    refresh_interval_seconds: 60,
    revalidating: false,
    rows: [],
    market: {
      is_open: true,
      session: "regular",
      reason: null,
      last_completed_session: "2026-09-11",
      next_open: "2026-09-15T13:30:00Z",
      next_close: "2026-09-14T20:00:00Z",
      ...market,
    },
  };
}

function row(source: string | null, signalSource: string | null): MarketRow {
  const signal = signalSource === null ? null : ({ source: signalSource } as Signal);
  return { symbol: "AAPL", source, signal } as MarketRow;
}

describe("simulatedParts", () => {
  it("separates simulated signals from simulated prices", () => {
    // The state with a quote key but no daily-bar key: live prices, invented history.
    const board = { ...dashboard({}), rows: [row("finnhub", "simulated")] };
    expect(simulatedParts(board)).toEqual({ prices: false, signals: true });
  });

  it("reports both when nothing is real", () => {
    const board = { ...dashboard({}), rows: [row("simulated", "simulated")] };
    expect(simulatedParts(board)).toEqual({ prices: true, signals: true });
  });

  it("reports neither when everything is real, including rows without a signal", () => {
    const board = { ...dashboard({}), rows: [row("finnhub", "twelvedata"), row("finnhub", null)] };
    expect(simulatedParts(board)).toEqual({ prices: false, signals: false });
  });
});

describe("marketHeadline", () => {
  it("says when an open market closes", () => {
    expect(marketHeadline(dashboard({}))).toBe("Market open · closes 4:00 PM ET");
  });

  it("says a closed market is showing the last close, and when it reopens", () => {
    const closed = dashboard({
      is_open: false,
      session: "closed",
      reason: "Market closed · Weekend",
      next_open: "2026-09-14T13:30:00Z",
      next_close: null,
    });
    expect(marketHeadline(closed)).toBe(
      "Market closed · Weekend · showing Fri, Sep 11 close · opens Mon 9:30 AM ET",
    );
  });
});

describe("serverNow", () => {
  it("measures age on the server clock even when the browser clock is wrong", () => {
    const browserClockTenMinutesFast = Date.parse("2026-09-14T16:10:00Z");
    const receivedAt = browserClockTenMinutesFast;
    const thirtySecondsLater = receivedAt + 30_000;
    expect(serverNow("2026-09-14T16:00:00Z", receivedAt, thirtySecondsLater).toISOString()).toBe(
      "2026-09-14T16:00:30.000Z",
    );
  });

  it("never runs backwards if the browser clock jumps back", () => {
    const receivedAt = 1_000_000;
    expect(serverNow("2026-09-14T16:00:00Z", receivedAt, receivedAt - 5_000).toISOString()).toBe(
      "2026-09-14T16:00:00.000Z",
    );
  });
});

describe("stream fallback", () => {
  it("retries a few times, then falls back to polling", () => {
    for (let errors = 1; errors < MAX_STREAM_ERRORS; errors++) {
      expect(streamErrorAction(errors)).toBe("retry");
    }
    expect(streamErrorAction(MAX_STREAM_ERRORS)).toBe("fallback");
  });
});

describe("signedNumber", () => {
  it("puts a plus on positive contributions only", () => {
    expect(signedNumber(4.25)).toBe("+4.3");
    expect(signedNumber(-4.25)).toBe("-4.3");
    expect(signedNumber(0)).toBe("0.0");
  });
});
