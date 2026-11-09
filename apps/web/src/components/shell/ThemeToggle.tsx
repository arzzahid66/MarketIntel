"use client";

/**
 * Light / dark / system, as a three-way segmented control.
 *
 * "System" is a real option, not an implicit default the reader cannot get back
 * to: someone whose laptop switches at sunset should be able to ask for that
 * rather than being pinned to whatever they last clicked.
 *
 * The write goes to a route handler which sets the cookie, then `router.refresh()`
 * re-renders the server tree so `<html data-theme>` matches. The optimistic
 * local state is only so the pressed segment responds instantly.
 */

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import type { ThemePreference } from "@/lib/theme";

const OPTIONS: { value: ThemePreference; label: string; title: string }[] = [
  { value: "light", label: "Light", title: "Always light" },
  { value: "dark", label: "Dark", title: "Always dark" },
  { value: "system", label: "Auto", title: "Follow my system setting" },
];

export function ThemeToggle({ current }: { current: ThemePreference }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [choice, setChoice] = useState<ThemePreference>(current);

  function select(theme: ThemePreference) {
    if (theme === choice) return;
    setChoice(theme);
    startTransition(async () => {
      try {
        await fetch("/api/theme", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ theme }),
        });
        router.refresh();
      } catch {
        // The cookie did not get set, so the page is still on the old theme.
        // Put the control back rather than showing a choice that is not real.
        setChoice(current);
      }
    });
  }

  return (
    <div
      role="group"
      aria-label="Colour theme"
      className="hidden items-center rounded-[var(--radius-ui)] border border-line sm:inline-flex"
    >
      {OPTIONS.map((option) => {
        const active = choice === option.value;
        return (
          <button
            key={option.value}
            type="button"
            title={option.title}
            aria-pressed={active}
            disabled={pending}
            onClick={() => select(option.value)}
            className={`h-8 px-2.5 text-small first:rounded-l-[var(--radius-ui)] last:rounded-r-[var(--radius-ui)] ${
              active ? "bg-line font-medium text-ink" : "text-muted hover:text-ink"
            } disabled:opacity-60`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
