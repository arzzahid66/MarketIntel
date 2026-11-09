"use client";

/**
 * Route-level error boundary. Sentry captures the exception via the Next
 * integration; the user gets a recoverable state rather than a blank page.
 */

import { useEffect } from "react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Panel } from "@/components/ui/Panel";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Structured, not a bare console.log, so it is greppable in the browser too.
    console.error("route_error", { message: error.message, digest: error.digest });
  }, [error]);

  return (
    <Panel>
      <EmptyState
        title="Something went wrong"
        description="The page failed to render. This has been reported. Trying again often works."
        action={
          <Button variant="secondary" size="sm" onClick={reset}>
            Try again
          </Button>
        }
      />
    </Panel>
  );
}
