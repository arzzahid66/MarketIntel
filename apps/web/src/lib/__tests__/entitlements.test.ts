import { describe, expect, it } from "vitest";

import { bandForScore } from "@/components/ui/SignalBadge";
import { can, isUnlimited, limitOf, stringOf } from "@/lib/entitlements";
import { FEATURE, UNLIMITED } from "@/lib/types";
import type { Entitlements } from "@/lib/types";

function entitlements(features: Record<string, boolean | number | string>): Entitlements {
  return {
    plan_code: "test",
    plan_name: "Test",
    subscription_status: "active",
    features,
  };
}

describe("can", () => {
  it("reads a boolean feature directly", () => {
    expect(can(entitlements({ [FEATURE.CHAT_CAN_POST]: true }), FEATURE.CHAT_CAN_POST)).toBe(true);
    expect(can(entitlements({ [FEATURE.CHAT_CAN_POST]: false }), FEATURE.CHAT_CAN_POST)).toBe(
      false,
    );
  });

  it("treats a zero limit as denied and unlimited as allowed", () => {
    expect(can(entitlements({ [FEATURE.CUSTOM_TICKER_LIMIT]: 0 }), FEATURE.CUSTOM_TICKER_LIMIT)).toBe(
      false,
    );
    expect(
      can(entitlements({ [FEATURE.CUSTOM_TICKER_LIMIT]: UNLIMITED }), FEATURE.CUSTOM_TICKER_LIMIT),
    ).toBe(true);
  });

  it("fails closed when there is no session or no key", () => {
    expect(can(null, FEATURE.CHAT_CAN_POST)).toBe(false);
    expect(can(entitlements({}), FEATURE.CHAT_CAN_POST)).toBe(false);
  });
});

describe("limitOf / isUnlimited / stringOf", () => {
  it("returns 0 rather than NaN for a missing numeric key", () => {
    expect(limitOf(entitlements({}), FEATURE.AI_MESSAGES_PER_DAY)).toBe(0);
  });

  it("detects the unlimited sentinel", () => {
    expect(
      isUnlimited(entitlements({ [FEATURE.AI_MESSAGES_PER_DAY]: UNLIMITED }), FEATURE.AI_MESSAGES_PER_DAY),
    ).toBe(true);
  });

  it("returns an empty string for a missing string key", () => {
    expect(stringOf(entitlements({}), FEATURE.EXTENDED_MARKETS_ACCESS)).toBe("");
    expect(
      stringOf(
        entitlements({ [FEATURE.EXTENDED_MARKETS_ACCESS]: "full" }),
        FEATURE.EXTENDED_MARKETS_ACCESS,
      ),
    ).toBe("full");
  });
});

describe("bandForScore", () => {
  it("matches the section 4 thresholds exactly at the boundaries", () => {
    expect(bandForScore(-41)).toBe("strong_bearish");
    expect(bandForScore(-40)).toBe("bearish");
    expect(bandForScore(-16)).toBe("bearish");
    expect(bandForScore(-15)).toBe("neutral");
    expect(bandForScore(0)).toBe("neutral");
    expect(bandForScore(15)).toBe("neutral");
    expect(bandForScore(16)).toBe("bullish");
    expect(bandForScore(40)).toBe("bullish");
    expect(bandForScore(41)).toBe("strong_bullish");
  });

  it("shows a pending state rather than inventing Neutral when there is no score", () => {
    expect(bandForScore(null)).toBe("pending");
    expect(bandForScore(undefined)).toBe("pending");
  });
});
