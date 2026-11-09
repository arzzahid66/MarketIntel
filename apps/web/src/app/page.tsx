/**
 * The homepage.
 *
 * Section 6: the logged-out hero *is* the live dashboard. No marketing headline
 * above real data - show the product working. The table renders on the server
 * from cache and database (never waiting on a data provider), then the client
 * component keeps it live.
 */

import Link from "next/link";

import { LiveDashboard } from "@/components/dashboard/LiveDashboard";
import { TickerTable } from "@/components/dashboard/TickerTable";
import { FeedPanel } from "@/components/feed/FeedPanel";
import { Alert } from "@/components/ui/Alert";
import { EmptyState } from "@/components/ui/EmptyState";
import { Panel } from "@/components/ui/Panel";
import { apiFetchOrNull } from "@/lib/api";
import { getAccessToken, getSession } from "@/lib/session";
import type { Dashboard, Feed } from "@/lib/types";

export default async function HomePage() {
  const token = await getAccessToken();
  const auth = token ? { accessToken: token } : {};
  // Fetched together: the feed is free for everyone, so it never waits on the
  // session, and a failing feed must not take the dashboard down with it.
  const [dashboard, feed, session] = await Promise.all([
    apiFetchOrNull<Dashboard>("/market/dashboard", auth),
    apiFetchOrNull<Feed>("/feed?limit=25", auth),
    getSession().catch(() => null),
  ]);

  return (
    <div className="flex flex-col gap-8">
      {dashboard ? (
        <LiveDashboard initial={dashboard} />
      ) : (
        <div className="flex flex-col gap-4">
          <h1 className="text-xl font-semibold tracking-tight">Big 7</h1>
          <Alert tone="error">
            Market data is unavailable right now. This is a problem on our side, not a market
            move — the page will recover as soon as the service does.
          </Alert>
          <Panel>
            <div className="px-4 pt-4">
              <TickerTable rows={[]} loading />
            </div>
          </Panel>
        </div>
      )}

      {feed ? (
        <FeedPanel initial={feed} />
      ) : (
        <Panel title="News & social feed">
          <EmptyState
            title="The feed is unavailable right now"
            description="This is a problem on our side. Headlines will reappear as soon as the service recovers."
            action={
              !session && (
                <Link href="/pricing" className="text-small">
                  See what each plan includes
                </Link>
              )
            }
          />
        </Panel>
      )}
    </div>
  );
}
