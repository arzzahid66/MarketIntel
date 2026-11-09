import { describe, expect, it } from "vitest";

import { quotaMessage, remaining } from "@/components/analyst/AnalystChat";
import type { AnalystUsage } from "@/lib/types";

function usage(partial: Partial<AnalystUsage>): AnalystUsage {
  return {
    used_today: 0,
    daily_limit: 5,
    used_this_hour: 0,
    hourly_limit: 5,
    ...partial,
  };
}

describe("remaining", () => {
  it("counts a capped plan against its ceiling", () => {
    expect(remaining(usage({ used_today: 3 }))).toBe("3 of 5 used today · 0 of 5 this hour");
  });

  it("says fair use rather than printing -1 at the reader", () => {
    const pro = usage({ daily_limit: -1, used_today: 120, hourly_limit: 40, used_this_hour: 2 });
    expect(remaining(pro)).toBe("Fair use · 2 of 40 this hour");
  });

  it("omits the hourly clause when there is no hourly ceiling", () => {
    expect(remaining(usage({ daily_limit: -1, hourly_limit: -1 }))).toBe("Fair use");
  });
});

describe("quotaMessage", () => {
  it("names the window that actually ran out", () => {
    expect(quotaMessage({ window: "day", limit: 5 })).toBe(
      "You have used all 5 analyst questions for today.",
    );
    expect(quotaMessage({ window: "hour", limit: 20 })).toBe(
      "You have used all 20 analyst questions for this hour.",
    );
  });

  it("stays readable when the API sends no detail", () => {
    // A 402 from a proxy, say: still not an error the reader caused.
    expect(quotaMessage(undefined)).toBe("You have used your allowance for today.");
  });
});
