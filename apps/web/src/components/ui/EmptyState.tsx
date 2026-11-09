/**
 * Empty states are part of the shell, built before any feature (section 6), so
 * no screen ever ships with a blank rectangle where data has not arrived yet.
 */

import type { ReactNode } from "react";

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <p className="font-medium text-ink">{title}</p>
      <p className="max-w-md text-small text-muted">{description}</p>
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
