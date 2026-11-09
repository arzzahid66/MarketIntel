import type { Metadata } from "next";

import { Alert } from "@/components/ui/Alert";
import { Panel } from "@/components/ui/Panel";

export const metadata: Metadata = { title: "Privacy Policy" };

/** Placeholder. See legal/terms/page.tsx - Phase 5 blocker, lawyer-reviewed. */
export default function PrivacyPage() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <h1 className="text-xl font-semibold tracking-tight">Privacy Policy</h1>
      <Alert>
        Not yet drafted. Phase 5 delivers this alongside cookie consent and the GDPR
        data-export and delete endpoints.
      </Alert>
      <Panel className="p-4">
        <p className="text-small text-muted">
          Today the platform stores only an email address, an optional display name and
          a password hash. Passwords are hashed with bcrypt and never stored in clear.
        </p>
      </Panel>
    </div>
  );
}
