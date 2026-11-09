/**
 * The legal floor (build plan section 3): every page carrying a signal or AI
 * output shows a persistent "Informational only - not financial advice" line.
 *
 * It lives in the root layout rather than in individual pages so a new screen
 * cannot ship without it.
 */

export function Disclaimer() {
  return (
    <p className="text-small text-muted">
      Informational only — not financial advice. Signals are computed from public
      market data and may be delayed.
    </p>
  );
}
