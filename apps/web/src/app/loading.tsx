import { TickerTable } from "@/components/dashboard/TickerTable";
import { Panel } from "@/components/ui/Panel";

/**
 * Shown while a server component streams. It renders the real TickerTable in
 * its loading state - same scroll wrapper, same column widths, same row height -
 * so the skeleton cannot drift from the table it stands in for.
 */
export default function Loading() {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <span className="skeleton block h-7 w-32" />
        <span className="skeleton block h-3.5 w-64" />
      </div>
      <Panel>
        <div className="px-4 pt-4">
          <TickerTable rows={[]} loading />
        </div>
      </Panel>
    </div>
  );
}
