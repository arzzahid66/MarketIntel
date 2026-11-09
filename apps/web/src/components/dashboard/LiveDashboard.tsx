"use client";

/**
 * The live Big 7 dashboard.
 *
 * Renders immediately from the server-rendered snapshot, then keeps itself
 * current:
 *
 *   1. Server-sent events from /api/market/stream. The server pushes a fresh
 *      snapshot when the worker ingests new data, at most once per the viewer's
 *      plan interval (Free 5 min, Plus 60 s, Pro 15 s).
 *   2. If the stream fails MAX_STREAM_ERRORS times in a row (a proxy that
 *      buffers SSE, a corporate network), it falls back to polling on the same
 *      plan interval.
 *   3. The refresh button asks the server for fresh data. The server decides
 *      whether that is worth a provider call; the button cannot force one.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { TickerTable } from "@/components/dashboard/TickerTable";
import { Alert } from "@/components/ui/Alert";
import { LastUpdated } from "@/components/ui/LastUpdated";
import { Panel } from "@/components/ui/Panel";
import {
  formatExchangeTime,
  marketHeadline,
  simulatedParts,
  streamErrorAction,
} from "@/lib/market";
import type { Transport } from "@/lib/market";
import type { Dashboard } from "@/lib/types";

/** Wait this long after a refresh that started a background fetch, then re-read. */
const REVALIDATE_FOLLOW_UP_MS = 2500;

/**
 * Names exactly which numbers are simulated.
 *
 * Signals can be simulated while prices are live: the signal is computed from
 * daily bars, and a quote key alone does not buy those. A score built on
 * invented history is not a weak signal, it is not a signal at all, so the
 * notice says so rather than implying the prices are fake too.
 */
function SimulatedNotice({ data }: { data: Dashboard }) {
  const { prices, signals } = simulatedParts(data);

  if (signals && !prices) {
    return (
      <Alert>
        <strong className="font-semibold text-ink">Simulated signals.</strong> Prices are live,
        but the price history each signal is computed from is generated for development — treat
        the scores as placeholders until historical data is connected.
      </Alert>
    );
  }
  if (prices && !signals) {
    return (
      <Alert>
        <strong className="font-semibold text-ink">Simulated prices.</strong> These prices are
        generated for development and are not real market data.
      </Alert>
    );
  }
  return (
    <Alert>
      <strong className="font-semibold text-ink">Simulated data.</strong> These prices and signals
      are generated for development and are not real market data.
    </Alert>
  );
}

interface Received {
  data: Dashboard;
  /** Browser clock when the payload arrived - only ever used to measure elapsed time. */
  receivedAt: number;
}

export function LiveDashboard({ initial }: { initial: Dashboard }) {
  const [received, setReceived] = useState<Received>(() => ({
    data: initial,
    receivedAt: Date.now(),
  }));
  const [transport, setTransport] = useState<Transport>("connecting");
  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const intervalSeconds = useRef(initial.refresh_interval_seconds);

  const accept = useCallback((data: Dashboard) => {
    intervalSeconds.current = data.refresh_interval_seconds;
    setReceived({ data, receivedAt: Date.now() });
  }, []);

  const pollOnce = useCallback(async () => {
    const response = await fetch("/api/market/dashboard", { cache: "no-store" });
    if (response.ok) accept((await response.json()) as Dashboard);
  }, [accept]);

  useEffect(() => {
    let source: EventSource | null = null;
    let pollTimer: number | undefined;
    let consecutiveErrors = 0;
    let stopped = false;

    const schedulePoll = () => {
      pollTimer = window.setTimeout(async () => {
        if (stopped) return;
        await pollOnce().catch(() => undefined);
        schedulePoll();
      }, intervalSeconds.current * 1000);
    };

    const fallBackToPolling = () => {
      source?.close();
      source = null;
      setTransport("polling");
      schedulePoll();
    };

    if (typeof EventSource === "undefined") {
      pollTimer = window.setTimeout(fallBackToPolling, 0);
    } else {
      source = new EventSource("/api/market/stream");
      source.onopen = () => {
        consecutiveErrors = 0;
        setTransport("streaming");
      };
      source.addEventListener("snapshot", (event) => {
        consecutiveErrors = 0;
        setTransport("streaming");
        try {
          accept(JSON.parse((event as MessageEvent<string>).data) as Dashboard);
        } catch {
          // A malformed frame is skipped; the next snapshot replaces it.
        }
      });
      source.onerror = () => {
        consecutiveErrors += 1;
        if (streamErrorAction(consecutiveErrors) === "fallback") fallBackToPolling();
        // Otherwise EventSource reconnects by itself after the server's retry hint.
      };
    }

    return () => {
      stopped = true;
      source?.close();
      window.clearTimeout(pollTimer);
    };
  }, [accept, pollOnce]);

  const refresh = async () => {
    setRefreshing(true);
    setNotice(null);
    try {
      const response = await fetch("/api/market/refresh", { method: "POST" });
      if (response.status === 429) {
        setNotice("Refreshed a moment ago. Try again in a few seconds.");
        return;
      }
      if (!response.ok) {
        setNotice("Could not refresh right now. Showing the last known prices.");
        return;
      }
      const data = (await response.json()) as Dashboard;
      accept(data);
      if (data.revalidating) {
        window.setTimeout(() => void pollOnce().catch(() => undefined), REVALIDATE_FOLLOW_UP_MS);
      }
    } catch {
      setNotice("Could not reach the service. Showing the last known prices.");
    } finally {
      setRefreshing(false);
    }
  };

  const { data, receivedAt } = received;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Big 7</h1>
          <p className="mt-1 text-small text-muted">{marketHeadline(data)}</p>
        </div>
        <LastUpdated
          updatedAt={data.last_updated_at}
          serverTime={data.server_time}
          receivedAt={receivedAt}
          onRefresh={refresh}
          refreshing={refreshing}
          transport={transport}
        />
      </div>

      {data.is_simulated && <SimulatedNotice data={data} />}

      {data.data_status === "stale" && (
        <Alert tone="error">
          Data delayed — showing the last known prices
          {data.last_updated_at ? ` from ${formatExchangeTime(data.last_updated_at)}` : ""}. We
          are retrying automatically.
        </Alert>
      )}

      {data.data_status === "unavailable" && (
        <Alert>Prices have not arrived yet. They will appear here as soon as they do.</Alert>
      )}

      {notice && (
        <p role="status" className="text-small text-muted">
          {notice}
        </p>
      )}

      <Panel>
        <div className="px-4 pt-4">
          <TickerTable rows={data.rows} />
        </div>
        <p className="border-t border-line px-4 py-3 text-small text-muted">
          Signals are a fixed formula over price trend, momentum, returns, volume and news
          sentiment from the feed below — hover a badge to see how each score was built.
        </p>
      </Panel>
    </div>
  );
}
