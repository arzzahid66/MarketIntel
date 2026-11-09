/**
 * The protected page that proves the Phase 1 exit criterion end to end:
 * signup -> login -> a page only an authenticated user can see.
 *
 * It also shows the resolved entitlements, which is the most useful thing to
 * put in front of the client: it makes the plan matrix visible and verifiable
 * before any paid feature exists.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Panel } from "@/components/ui/Panel";
import { EmptyState } from "@/components/ui/EmptyState";
import { Alert } from "@/components/ui/Alert";
import { isUnlimited, limitOf, stringOf } from "@/lib/entitlements";
import { formatInterval, formatLimit } from "@/lib/format";
import { getSession } from "@/lib/session";
import { FEATURE } from "@/lib/types";

export const metadata: Metadata = { title: "Your dashboard" };

export default async function DashboardPage() {
  const session = await getSession();

  // Middleware already redirects, but a server-side check means the page is
  // never renderable without a session even if the matcher changes.
  if (!session) redirect("/login?next=%2Fdashboard");

  const { user, entitlements } = session;
  const tickerLimit = limitOf(entitlements, FEATURE.CUSTOM_TICKER_LIMIT);
  const aiPerDay = limitOf(entitlements, FEATURE.AI_MESSAGES_PER_DAY);
  const refresh = limitOf(entitlements, FEATURE.REFRESH_INTERVAL_SECONDS);
  const marketsAccess = stringOf(entitlements, FEATURE.EXTENDED_MARKETS_ACCESS);

  const rows: Array<[string, string]> = [
    ["Plan", entitlements.plan_name],
    ["Subscription status", entitlements.subscription_status ?? "none"],
    ["Custom tickers", formatLimit(tickerLimit)],
    ["AI analyst messages", isUnlimited(entitlements, FEATURE.AI_MESSAGES_PER_DAY) ? "Fair use" : `${aiPerDay} / day`],
    ["Extended markets", marketsAccess === "full" ? "Full" : "Delayed / partial"],
    ["Chatrooms", entitlements.features[FEATURE.CHAT_CAN_POST] ? "Read + post" : "Read-only"],
    ["Data refresh", formatInterval(refresh)],
  ];

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">
          {user.display_name || user.email}
        </h1>
        <p className="mt-1 text-small text-muted">
          Signed in as {user.email}
          {user.is_admin ? " · admin" : ""}
        </p>
      </div>

      <Panel title="Your access">
        <table className="w-full border-collapse text-body">
          <tbody>
            {rows.map(([label, value]) => (
              <tr key={label} className="border-t border-line first:border-t-0">
                <th scope="row" className="px-4 py-2.5 text-left font-normal text-muted">
                  {label}
                </th>
                <td className="px-4 py-2.5 text-right font-mono">{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="border-t border-line px-4 py-3 text-small text-muted">
          Resolved from the subscriptions table on this request — not from your login
          token. A plan change takes effect on the next page load.
        </p>
      </Panel>

      <Panel title="Custom tickers">
        {tickerLimit === 0 ? (
          <EmptyState
            title="Custom tickers are a Plus feature"
            description="The Free plan shows the Big 7. Plus adds 15 tickers of your own, Pro removes the limit."
            action={
              <Link href="/pricing" className="text-small">
                Compare plans
              </Link>
            }
          />
        ) : (
          <EmptyState
            title="No tickers added yet"
            description={`Your plan allows ${formatLimit(tickerLimit)} custom tickers. Adding and reordering them arrives with the paid dashboard in Phase 4.`}
          />
        )}
      </Panel>

      <Alert>
        Phase 1 delivers the authenticated shell, the plan matrix and the access rules.
        Live prices arrive in Phase 2, the news feed in Phase 3, and billing in Phase 4.
      </Alert>
    </div>
  );
}
