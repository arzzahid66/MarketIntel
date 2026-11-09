/**
 * Inline messages. Only the error variant carries colour, and it borrows
 * `--bear` because that is the app's single "something is wrong" red - no new
 * hues enter the palette for UI chrome.
 */

import type { ReactNode } from "react";

type Tone = "neutral" | "error";

export function Alert({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  const styles =
    tone === "error"
      ? "border-bear/40 bg-bear-wash text-bear"
      : "border-line bg-bg text-muted";

  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-[var(--radius-ui)] border px-3 py-2 text-small ${styles}`}
    >
      {children}
    </div>
  );
}
