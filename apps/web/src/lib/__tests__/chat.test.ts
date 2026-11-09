import { describe, expect, it } from "vitest";

import { refusalMessage } from "@/components/chat/ChatRoom";

describe("refusalMessage", () => {
  it("treats a rate limit as a wait, not a sale", () => {
    const message = refusalMessage(429, { message: "You can post 10 messages every 5 minutes." });
    expect(message).toBe("You can post 10 messages every 5 minutes.");
    expect(message).not.toMatch(/plan|upgrade/i);
  });

  it("treats a plan gate as an upgrade, not a failure", () => {
    expect(refusalMessage(402, { error: "upgrade_required" })).toMatch(/Plus plan/);
  });

  it("names a repeat post rather than saying something went wrong", () => {
    expect(refusalMessage(400, { error: "duplicate" })).toBe(
      "You have already posted that message.",
    );
  });

  it("stays readable when the API sends no detail", () => {
    expect(refusalMessage(500, undefined)).toBe("That message could not be posted.");
  });
});
