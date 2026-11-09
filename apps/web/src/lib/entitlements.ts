/**
 * Client-side entitlement *hints*.
 *
 * These exist so an upgrade prompt appears before the user hits a wall. They
 * are not a security boundary: the server re-checks every gated call and a
 * tampered client just gets a 402. Never gate anything that matters on these.
 */

import type { Entitlements, FeatureKey, FeatureValue } from "@/lib/types";
import { UNLIMITED } from "@/lib/types";

export function featureValue(
  entitlements: Entitlements | null,
  key: FeatureKey,
): FeatureValue | undefined {
  return entitlements?.features[key];
}

export function can(entitlements: Entitlements | null, key: FeatureKey): boolean {
  const value = featureValue(entitlements, key);
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value === UNLIMITED || value > 0;
  return value !== undefined;
}

/** Numeric ceiling, or 0 when the key is missing or not numeric. */
export function limitOf(entitlements: Entitlements | null, key: FeatureKey): number {
  const value = featureValue(entitlements, key);
  return typeof value === "number" ? value : 0;
}

export function isUnlimited(entitlements: Entitlements | null, key: FeatureKey): boolean {
  return limitOf(entitlements, key) === UNLIMITED;
}

export function stringOf(entitlements: Entitlements | null, key: FeatureKey): string {
  const value = featureValue(entitlements, key);
  return typeof value === "string" ? value : "";
}
