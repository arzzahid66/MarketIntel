/**
 * Browser-facing feed, used when the reader changes category filter.
 *
 * The browser calls this Next.js route, which calls FastAPI. Same rule as the
 * market routes: the browser never reaches a data source directly, and never
 * holds a token.
 */

import { NextResponse } from "next/server";

import { ApiError, apiFetch } from "@/lib/api";
import { getAccessToken } from "@/lib/session";
import type { Feed } from "@/lib/types";

export async function GET(request: Request) {
  const token = await getAccessToken();
  const incoming = new URL(request.url).searchParams;

  // Only forward parameters the API defines, so a crafted query cannot be
  // passed through to the backend untouched.
  const query = new URLSearchParams();
  for (const key of ["category", "symbol", "limit"]) {
    const value = incoming.get(key);
    if (value) query.set(key, value);
  }
  const suffix = query.toString();

  try {
    const feed = await apiFetch<Feed>(`/feed${suffix ? `?${suffix}` : ""}`, {
      ...(token ? { accessToken: token } : {}),
    });
    return NextResponse.json(feed, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    return NextResponse.json({ error: "feed_unavailable" }, { status });
  }
}
