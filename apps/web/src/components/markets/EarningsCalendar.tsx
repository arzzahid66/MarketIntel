/**
 * The earnings calendar.
 *
 * **It is earnings, not macro, and it says so.** The plan asks for an economic
 * calendar; Finnhub's free tier returns 403 on `/calendar/economic` and 200 on
 * `/calendar/earnings`, so this ships what is actually available and names it
 * honestly rather than relabelling earnings dates as economic events.
 *
 * Estimate and actual sit in adjacent columns because the gap between them is
 * the story. A scheduled event has no actual, and that cell reads "—" rather
 * than 0.00, which would look like a company that earned nothing.
 */

import type { EarningsEvent } from "@/lib/types";

const TIMING_LABEL: Record<string, string> = {
  bmo: "Before open",
  amc: "After close",
};

function eps(value: number | null): string {
  return value === null ? "—" : value.toFixed(2);
}

function surprise(event: EarningsEvent): { text: string; className: string } | null {
  if (event.eps_actual === null || event.eps_estimate === null) return null;
  const delta = event.eps_actual - event.eps_estimate;
  if (Math.abs(delta) < 0.005) return { text: "In line", className: "text-muted" };
  return {
    text: `${delta > 0 ? "+" : ""}${delta.toFixed(2)}`,
    className: delta > 0 ? "text-bull" : "text-bear",
  };
}

function formatDay(iso: string): string {
  // Parsed as a plain calendar date. `new Date("2026-11-17")` is UTC midnight,
  // which in a western timezone renders as the day before.
  const [year, month, day] = iso.split("-").map(Number);
  if (!year || !month || !day) return iso;
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

export function EarningsCalendarTable({ events }: { events: EarningsEvent[] }) {
  if (events.length === 0) {
    return (
      <p className="px-4 py-8 text-center text-small text-muted">
        No companies in our universe report in this window.
      </p>
    );
  }

  return (
    <table className="w-full border-collapse text-body">
      <thead>
        <tr className="border-b border-line text-left text-small text-muted">
          <th scope="col" className="px-4 py-2 font-medium">
            Date
          </th>
          <th scope="col" className="px-4 py-2 font-medium">
            Company
          </th>
          <th scope="col" className="px-4 py-2 font-medium">
            When
          </th>
          <th scope="col" className="px-4 py-2 text-right font-medium">
            EPS est.
          </th>
          <th scope="col" className="px-4 py-2 text-right font-medium">
            EPS actual
          </th>
          <th scope="col" className="px-4 py-2 text-right font-medium">
            Surprise
          </th>
        </tr>
      </thead>
      <tbody>
        {events.map((event) => {
          const delta = surprise(event);
          return (
            <tr key={`${event.symbol}-${event.session_date}`} className="border-b border-line">
              <td className="px-4 py-2 whitespace-nowrap">{formatDay(event.session_date)}</td>
              <th scope="row" className="px-4 py-2 text-left font-normal">
                <span className="font-medium">{event.symbol}</span>
                {event.name && <span className="text-muted"> {event.name}</span>}
              </th>
              <td className="px-4 py-2 text-small text-muted">
                {TIMING_LABEL[event.timing] ?? "—"}
              </td>
              <td className="px-4 py-2 text-right">{eps(event.eps_estimate)}</td>
              <td className="px-4 py-2 text-right">{eps(event.eps_actual)}</td>
              <td className={`px-4 py-2 text-right ${delta?.className ?? "text-muted"}`}>
                {delta?.text ?? "—"}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
