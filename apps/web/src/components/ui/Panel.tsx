/**
 * A bordered surface. Not a card - it has no shadow, no coloured header, and
 * no tinted background. Depth in this design comes from spacing.
 */

import type { ReactNode } from "react";

export function Panel({
  title,
  action,
  children,
  className = "",
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`border border-line bg-surface rounded-[var(--radius-ui)] ${className}`}
    >
      {(title || action) && (
        <header className="flex items-center justify-between gap-4 border-b border-line px-4 py-3">
          {title && <h2 className="text-lg font-semibold tracking-tight">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}
