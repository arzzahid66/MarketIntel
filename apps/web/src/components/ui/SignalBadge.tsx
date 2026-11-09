/**
 * The bullish/bearish badge (build plan section 4) and its breakdown.
 *
 * Colour here is meaning, the one job saturated colour has in this design. The
 * score is the deterministic composite computed by the worker - never an LLM -
 * and hovering or focusing the badge shows each component's contribution,
 * because explainability is the feature.
 */

import { BAND_LABEL, formatExchangeTime, signedNumber } from "@/lib/market";
import type { Signal } from "@/lib/types";

export type SignalBand =
  | "strong_bearish"
  | "bearish"
  | "neutral"
  | "bullish"
  | "strong_bullish"
  | "pending";

const LABEL: Record<SignalBand, string> = { ...BAND_LABEL, pending: "No signal yet" };

const TONE: Record<SignalBand, string> = {
  strong_bearish: "border-bear/40 bg-bear-wash text-bear",
  bearish: "border-bear/30 bg-bear-wash text-bear",
  neutral: "border-line bg-bg text-flat",
  bullish: "border-bull/30 bg-bull-wash text-bull",
  strong_bullish: "border-bull/40 bg-bull-wash text-bull",
  pending: "border-line bg-bg text-muted",
};

/** Section 4 thresholds. Tested against shared/signal_bands.json with the API's copy. */
export function bandForScore(score: number | null | undefined): SignalBand {
  if (score === null || score === undefined || Number.isNaN(score)) return "pending";
  if (score < -40) return "strong_bearish";
  if (score < -15) return "bearish";
  if (score <= 15) return "neutral";
  if (score <= 40) return "bullish";
  return "strong_bullish";
}

export function SignalBadge({ score, dimmed = false }: { score?: number | null; dimmed?: boolean }) {
  const band = bandForScore(score);
  return (
    <span
      className={`inline-flex h-6 items-center whitespace-nowrap rounded-[var(--radius-ui)] border px-2 text-small font-medium ${TONE[band]} ${dimmed ? "opacity-60" : ""}`}
    >
      {LABEL[band]}
      {band !== "pending" && score !== null && score !== undefined && (
        <span className="ml-1.5 tnum opacity-70">{signedNumber(score, 0)}</span>
      )}
    </span>
  );
}

/** Badge plus the hover/focus breakdown. Works without JavaScript. */
export function SignalCell({ signal, symbol }: { signal: Signal | null; symbol: string }) {
  if (!signal) return <SignalBadge score={null} />;

  const tooltipId = `signal-breakdown-${symbol}`;
  return (
    <div className="group relative inline-block">
      <button
        type="button"
        aria-describedby={tooltipId}
        className="rounded-[var(--radius-ui)]"
      >
        <SignalBadge score={signal.score} dimmed={signal.is_stale} />
      </button>
      <div
        role="tooltip"
        id={tooltipId}
        className="invisible absolute right-0 top-full z-20 mt-2 w-80 rounded-[var(--radius-ui)] border border-line bg-surface p-3 text-left text-small opacity-0 transition-opacity group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100"
      >
        <p className="font-medium text-ink">
          {BAND_LABEL[signal.band]} · score <span className="tnum">{signedNumber(signal.score)}</span>
        </p>
        <table className="mt-2 w-full border-collapse">
          <tbody>
            {signal.components.map((component) => (
              <tr key={component.key}>
                <th scope="row" className="py-0.5 pr-2 text-left font-normal text-muted">
                  {component.label}{" "}
                  <span className="tnum">({Math.round(component.weight * 100)}%)</span>
                </th>
                <td
                  className={`py-0.5 text-right font-mono ${
                    !component.available
                      ? "text-muted"
                      : component.contribution > 0
                        ? "text-bull"
                        : component.contribution < 0
                          ? "text-bear"
                          : "text-flat"
                  }`}
                >
                  {component.available ? signedNumber(component.contribution) : "n/a"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {signal.notes.map((note) => (
          <p key={note} className="mt-2 text-muted">
            {note}
          </p>
        ))}
        <p className="mt-2 text-muted">
          Computed {formatExchangeTime(signal.computed_at, false)}
          {signal.intraday ? " from today's live price" : " from the last close"} · formula v
          {signal.formula_version}
          {signal.is_stale ? " · out of date" : ""}
        </p>
      </div>
    </div>
  );
}
