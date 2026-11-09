/**
 * Skeleton loaders.
 *
 * The rule from section 6: a skeleton must match the final row height exactly.
 * `ROW_HEIGHT` is the single source of that number, shared by the real table
 * and its skeleton, so the two cannot drift and cause layout shift.
 */

/** Matches --spacing-row in globals.css and the real table row height. */
export const ROW_HEIGHT = 52;

export function Skeleton({ className = "" }: { className?: string }) {
  return <span aria-hidden="true" className={`skeleton block ${className}`} />;
}

export function SkeletonText({ width = "w-24" }: { width?: string }) {
  return <Skeleton className={`h-3.5 ${width}`} />;
}

/**
 * A placeholder row for the ticker table. Column widths mirror TickerTable so
 * the transition from loading to loaded moves nothing on screen.
 */
export function SkeletonTableRow({ columns }: { columns: string[] }) {
  return (
    <tr className="border-t border-line" style={{ height: ROW_HEIGHT }}>
      {columns.map((width, index) => (
        <td key={index} className="px-4">
          <Skeleton className={`h-3.5 ${width}`} />
        </td>
      ))}
    </tr>
  );
}

export function SkeletonTable({ columns, rows = 7 }: { columns: string[]; rows?: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, index) => (
        <SkeletonTableRow key={index} columns={columns} />
      ))}
    </>
  );
}
