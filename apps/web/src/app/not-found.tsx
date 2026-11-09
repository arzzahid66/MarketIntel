import Link from "next/link";

import { EmptyState } from "@/components/ui/EmptyState";
import { Panel } from "@/components/ui/Panel";

export default function NotFound() {
  return (
    <Panel>
      <EmptyState
        title="Page not found"
        description="That URL does not exist. It may have moved, or it may not be built yet."
        action={<Link href="/" className="text-small">Back to the dashboard</Link>}
      />
    </Panel>
  );
}
