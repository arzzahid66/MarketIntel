import type { Metadata } from "next";

import { Alert } from "@/components/ui/Alert";
import { Panel } from "@/components/ui/Panel";

export const metadata: Metadata = { title: "Terms of Service" };

/**
 * Placeholder. Terms of Service, Privacy Policy and cookie consent are Phase 5
 * launch blockers and the final text must be reviewed by the client's lawyer -
 * so this page states that plainly rather than shipping invented legal text.
 */
export default function TermsPage() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <h1 className="text-xl font-semibold tracking-tight">Terms of Service</h1>
      <Alert>
        Not yet drafted. This is a Phase 5 launch blocker: the final text must be
        reviewed by the client&apos;s lawyer before going live.
      </Alert>
      <Panel className="p-4">
        <p className="text-small text-muted">
          The platform is informational only and does not provide financial advice. No
          content on this site is a recommendation to buy or sell any security.
        </p>
      </Panel>
    </div>
  );
}
