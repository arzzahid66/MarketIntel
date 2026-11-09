/**
 * The refresh button. All debouncing happens in FastAPI (per-client cooldown,
 * a shared fetch lock, a freshness check) - this route only forwards the call,
 * plus the viewer's IP so the per-client cooldown sees the real browser rather
 * than this Next.js server.
 */

import { NextResponse } from "next/server";

import { API_URL } from "@/lib/api";
import { getAccessToken } from "@/lib/session";

export async function POST(request: Request) {
  const token = await getAccessToken();
  const forwardedFor = request.headers.get("x-forwarded-for");

  try {
    const upstream = await fetch(`${API_URL}/market/refresh`, {
      method: "POST",
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(forwardedFor ? { "X-Forwarded-For": forwardedFor } : {}),
      },
    });
    const body = await upstream.json().catch(() => ({ error: "bad_upstream_body" }));
    const headers: Record<string, string> = { "Cache-Control": "no-store" };
    const retryAfter = upstream.headers.get("Retry-After");
    if (retryAfter) headers["Retry-After"] = retryAfter;
    return NextResponse.json(body, { status: upstream.status, headers });
  } catch {
    return NextResponse.json({ error: "upstream_unavailable" }, { status: 502 });
  }
}
