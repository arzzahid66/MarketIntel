/**
 * Browser-facing AI analyst.
 *
 * The browser posts here; this route calls FastAPI with the viewer's httpOnly
 * access cookie. The browser never holds a token and never reaches a model
 * directly - the key, the quota and the prompt all stay server-side.
 *
 * A 402 is passed through with its body intact, because the body carries which
 * window ran out and how many were used. The page turns that into "5 of 5 used
 * today", which an error toast could not.
 */

import { NextResponse } from "next/server";

import { ApiError, apiFetch } from "@/lib/api";
import { getAccessToken } from "@/lib/session";
import type { AnalystAnswer } from "@/lib/types";

export async function POST(request: Request) {
  const token = await getAccessToken();
  if (!token) {
    return NextResponse.json({ error: "sign_in_required" }, { status: 401 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const { question, symbol } = (body ?? {}) as { question?: unknown; symbol?: unknown };
  if (typeof question !== "string") {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  try {
    const answer = await apiFetch<AnalystAnswer>("/ai/ask", {
      method: "POST",
      accessToken: token,
      body: { question, ...(typeof symbol === "string" && symbol ? { symbol } : {}) },
    });
    return NextResponse.json(answer, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json(error.body ?? { error: "analyst_failed" }, {
        status: error.status,
      });
    }
    return NextResponse.json({ error: "analyst_unavailable" }, { status: 502 });
  }
}
