/**
 * The AI analyst page.
 *
 * Gated the same way every paid surface is: it calls the feature-gated status
 * endpoint, and a 402 becomes an upgrade prompt rather than an error. The gate
 * is the API's answer, never a client-side plan check - `lib/entitlements` is
 * hints only.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { AnalystChat } from "@/components/analyst/AnalystChat";
import { EmptyState } from "@/components/ui/EmptyState";
import { Panel } from "@/components/ui/Panel";
import { ApiError, apiFetch } from "@/lib/api";
import { getAccessToken } from "@/lib/session";
import type { AnalystStatus } from "@/lib/types";

export const metadata: Metadata = { title: "AI analyst" };

type Gate =
  | { state: "ok"; status: AnalystStatus }
  | { state: "signed_out" }
  | { state: "upgrade"; plan: string | null }
  | { state: "unavailable" };

async function gate(): Promise<Gate> {
  const token = await getAccessToken();
  if (!token) return { state: "signed_out" };
  try {
    return { state: "ok", status: await apiFetch<AnalystStatus>("/ai/status", {
      accessToken: token,
    }) };
  } catch (error) {
    if (error instanceof ApiError && error.isUpgradeRequired) {
      const detail = error.body?.detail as { current_plan?: string } | undefined;
      return { state: "upgrade", plan: detail?.current_plan ?? null };
    }
    if (error instanceof ApiError && error.status === 401) return { state: "signed_out" };
    // An outage is not a reason to sell someone an upgrade.
    return { state: "unavailable" };
  }
}

export default async function AnalystPage() {
  const result = await gate();

  if (result.state === "signed_out") {
    return (
      <Panel title="AI analyst">
        <EmptyState
          title="Sign in to ask the analyst"
          description="The analyst answers from the news feed and cites every article it used. Free accounts include 5 questions a day."
          action={
            <Link href="/login" className="text-small">
              Log in or create an account
            </Link>
          }
        />
      </Panel>
    );
  }

  if (result.state === "upgrade") {
    return (
      <Panel title="AI analyst">
        <EmptyState
          title="The analyst is not included on your plan"
          description="Upgrade to ask questions about the news feed and get answers with citations."
          action={
            <Link href="/pricing" className="text-small">
              See what each plan includes
            </Link>
          }
        />
      </Panel>
    );
  }

  if (result.state === "unavailable") {
    return (
      <Panel title="AI analyst">
        <EmptyState
          title="The analyst is unavailable right now"
          description="This is a problem on our side, not your account. It will return as soon as the service does."
        />
      </Panel>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <AnalystChat initialUsage={result.status.usage} />
      {result.status.searchable_articles === 0 && (
        <p className="text-small text-muted">
          No articles are searchable yet — the feed is still being indexed. Answers will
          improve as it fills.
        </p>
      )}
    </div>
  );
}
