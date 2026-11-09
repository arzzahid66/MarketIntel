/**
 * The pricing page renders from GET /plans, so pricing and limits change with a
 * database row rather than a deploy. Nothing on this page is hardcoded except
 * the human labels for each feature key.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/Alert";
import { Panel } from "@/components/ui/Panel";
import { apiFetchOrNull } from "@/lib/api";
import { formatInterval, formatLimit, formatMonthlyPrice } from "@/lib/format";
import { getSession } from "@/lib/session";
import { FEATURE } from "@/lib/types";
import type { FeatureValue, Plan } from "@/lib/types";

export const metadata: Metadata = { title: "Pricing" };

/** Row order and wording for the matrix. Values always come from the API. */
const ROWS: Array<{ key: string; label: string }> = [
  { key: FEATURE.BIG7_DASHBOARD, label: "Big 7 dashboard" },
  { key: FEATURE.NEWS_FEED_ALL_CATEGORIES, label: "News / social feed (all categories)" },
  { key: FEATURE.CUSTOM_TICKER_LIMIT, label: "Custom tickers on dashboard" },
  { key: FEATURE.EXTENDED_MARKETS_ACCESS, label: "Sector heatmap + economic calendar" },
  { key: FEATURE.AI_MESSAGES_PER_DAY, label: "AI analyst messages" },
  { key: FEATURE.CHAT_CAN_POST, label: "Chatrooms" },
  { key: FEATURE.REFRESH_INTERVAL_SECONDS, label: "Data refresh interval" },
];

function renderValue(key: string, value: FeatureValue | undefined): string {
  if (value === undefined) return "—";

  switch (key) {
    case FEATURE.REFRESH_INTERVAL_SECONDS:
      return formatInterval(Number(value));
    case FEATURE.CUSTOM_TICKER_LIMIT:
      return formatLimit(Number(value));
    case FEATURE.AI_MESSAGES_PER_DAY:
      return Number(value) === -1 ? "Fair use" : `${value} / day`;
    case FEATURE.EXTENDED_MARKETS_ACCESS:
      return value === "full" ? "Full" : "Delayed / partial";
    case FEATURE.CHAT_CAN_POST:
      return value ? "Read + post" : "Read-only";
    default:
      if (typeof value === "boolean") return value ? "Yes" : "—";
      return String(value);
  }
}

export default async function PricingPage() {
  const [plans, session] = await Promise.all([
    apiFetchOrNull<Plan[]>("/plans"),
    getSession().catch(() => null),
  ]);

  if (!plans) {
    return (
      <Alert tone="error">
        Plans are unavailable right now. This page reads them from the API, so it will
        recover as soon as the service does.
      </Alert>
    );
  }

  const featureMaps = plans.map(
    (plan) =>
      new Map<string, FeatureValue>(plan.features.map((feature) => [feature.feature_key, feature.value])),
  );

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Plans</h1>
        <p className="mt-1 text-small text-muted">
          Prices below are placeholders until the plan matrix is signed off. Checkout
          arrives in Phase 4.
        </p>
      </div>

      <Panel>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] border-collapse text-body">
            <thead>
              <tr>
                <th scope="col" className="px-4 py-3 text-left text-small font-medium text-muted">
                  Capability
                </th>
                {plans.map((plan) => (
                  <th key={plan.code} scope="col" className="px-4 py-3 text-left">
                    <span className="block font-semibold">{plan.name}</span>
                    <span className="block font-mono text-small text-muted">
                      {formatMonthlyPrice(plan.price_cents_monthly, plan.currency)}
                      {plan.price_cents_monthly > 0 ? " / mo" : ""}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row) => (
                <tr key={row.key} className="border-t border-line">
                  <th scope="row" className="px-4 py-2.5 text-left font-normal text-muted">
                    {row.label}
                  </th>
                  {featureMaps.map((features, index) => (
                    <td key={plans[index]?.code ?? index} className="px-4 py-2.5 font-mono">
                      {renderValue(row.key, features.get(row.key))}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="border-t border-line px-4 py-3 text-small text-muted">
          Pro is fair-use rather than metered: no daily cap, but a documented hourly
          limit that keeps costs honest.
        </p>
      </Panel>

      {!session && (
        <p className="text-small text-muted">
          <Link href="/signup">Create a free account</Link> to see your resolved access.
        </p>
      )}
    </div>
  );
}
