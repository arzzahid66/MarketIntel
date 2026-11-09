/**
 * Browser-facing dashboard snapshot, used by the polling fallback.
 *
 * The browser calls this Next.js route, which calls FastAPI with the viewer's
 * httpOnly access cookie. The browser never talks to a data provider, and never
 * holds a token.
 */

import { NextResponse } from "next/server";

import { ApiError, apiFetch } from "@/lib/api";
import { getAccessToken } from "@/lib/session";
import type { Dashboard } from "@/lib/types";

export async function GET() {
  const token = await getAccessToken();
  try {
    const dashboard = await apiFetch<Dashboard>("/market/dashboard", {
      ...(token ? { accessToken: token } : {}),
    });
    return NextResponse.json(dashboard, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    return NextResponse.json({ error: "dashboard_unavailable" }, { status });
  }
}
