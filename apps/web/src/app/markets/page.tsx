/**
 * Extended markets — the first paywalled surface, now real.
 *
 * **The gate is not a 402 here**, and that is deliberate. The plan matrix gives
 * Free "Delayed / partial" rather than nothing, so `markets.extended_access` is
 * a *string* feature (`full` | `delayed`) that the API reads per request and
 * uses to build a smaller payload. Free sees every sector tile; Plus and Pro
 * additionally see the companies inside each one and the full forward calendar.
 *
 * Both panels degrade independently: if the calendar API is down the heatmap
 * still renders. One dead endpoint must not blank a page.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { EarningsCalendarTable } from "@/components/markets/EarningsCalendar";
import { SectorHeatmap } from "@/components/markets/SectorHeatmap";
import { SectorTable } from "@/components/markets/SectorTable";
import { Alert } from "@/components/ui/Alert";
import { EmptyState } from "@/components/ui/EmptyState";
import { Panel } from "@/components/ui/Panel";
import { apiFetchOrNull } from "@/lib/api";
import { getAccessToken } from "@/lib/session";
import type { EarningsCalendar, Heatmap } from "@/lib/types";

export const metadata: Metadata = { title: "Extended markets" };

/** Always current: prices move, and a cached heatmap is a wrong heatmap. */
export const dynamic = "force-dynamic";

/** A plain calendar date. `new Date("2026-11-17")` is UTC midnight, which in a
 *  western timezone renders as the day before. */
function day(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

function windowLabel(since: string, until: string): string {
  return `${day(since)} – ${day(until)}`;
}

export default async function MarketsPage() {
  const token = await getAccessToken();
  const auth = token ? { accessToken: token } : {};

  const [heatmap, calendar] = await Promise.all([
    apiFetchOrNull<Heatmap>("/market/heatmap", auth),
    apiFetchOrNull<EarningsCalendar>("/market/calendar", auth),
  ]);

  const access = heatmap?.access ?? calendar?.access ?? "delayed";
  const isFull = access === "full";

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Extended markets</h1>
        <p className="mt-1 text-small text-muted">
          Sector heatmap and earnings calendar across{" "}
          {heatmap ? `${heatmap.total} companies` : "the wider universe"} ·{" "}
          {isFull ? "Full access" : "Delayed / partial on your plan"}
        </p>
      </div>

      {heatmap?.is_simulated && (
        <Alert>
          Simulated prices. These sector moves are generated for development and
          are not real market data.
        </Alert>
      )}

      <Panel
        title="Sector heatmap"
        action={
          heatmap && (
            <span className="text-small text-muted">
              {heatmap.covered} of {heatmap.total} priced
            </span>
          )
        }
      >
        {heatmap ? (
          <>
            <SectorHeatmap tiles={heatmap.tiles} />
            <div className="border-t border-line">
              <SectorTable tiles={heatmap.tiles} />
            </div>
          </>
        ) : (
          <EmptyState
            title="Heatmap unavailable"
            description="The markets API did not answer. Your plan is unaffected — this is an outage, not a paywall."
          />
        )}
      </Panel>

      <Panel
        title="Earnings calendar"
        action={
          calendar && (
            <span className="text-small text-muted">
              {windowLabel(calendar.since, calendar.until)}
            </span>
          )
        }
      >
        {calendar ? (
          <>
            <EarningsCalendarTable events={calendar.events} />
            {!isFull && (
              <p className="border-t border-line px-4 py-3 text-small text-muted">
                Your plan shows {windowLabel(calendar.since, calendar.until)}. Plus
                and Pro reach to {day(calendar.full_until)} and break each sector
                into its constituent companies.{" "}
                <Link href="/pricing">Compare plans</Link>
              </p>
            )}
          </>
        ) : (
          <EmptyState
            title="Calendar unavailable"
            description="The markets API did not answer. The heatmap above is unaffected."
          />
        )}
      </Panel>

      <p className="text-small text-muted">
        Earnings dates, not macroeconomic releases: our data provider&apos;s free
        tier does not serve an economic calendar. A macro feed needs a paid
        source, which is an open question for the client.
      </p>
    </div>
  );
}
