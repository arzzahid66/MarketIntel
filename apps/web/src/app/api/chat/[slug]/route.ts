/**
 * Browser-facing chatroom: history and posting.
 *
 * Same rule as every other surface - the browser talks to this Next route, and
 * this route attaches the httpOnly token. A 402 or 429 is passed through with
 * its body, because the composer needs to say *which* limit was hit: an upgrade
 * prompt and "you are posting too fast" are different messages.
 */

import { NextResponse } from "next/server";

import { ApiError, apiFetch } from "@/lib/api";
import { getAccessToken } from "@/lib/session";
import type { ChatHistory } from "@/lib/types";

async function proxy<T>(call: () => Promise<T>) {
  try {
    return NextResponse.json(await call(), { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json(error.body ?? { error: "chat_failed" }, { status: error.status });
    }
    return NextResponse.json({ error: "chat_unavailable" }, { status: 502 });
  }
}

export async function GET(_request: Request, context: { params: Promise<{ slug: string }> }) {
  const token = await getAccessToken();
  if (!token) return NextResponse.json({ error: "sign_in_required" }, { status: 401 });
  const { slug } = await context.params;
  return proxy(() =>
    apiFetch<ChatHistory>(`/chat/rooms/${encodeURIComponent(slug)}`, { accessToken: token }),
  );
}

export async function POST(request: Request, context: { params: Promise<{ slug: string }> }) {
  const token = await getAccessToken();
  if (!token) return NextResponse.json({ error: "sign_in_required" }, { status: 401 });
  const { slug } = await context.params;

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }
  const { body } = (payload ?? {}) as { body?: unknown };
  if (typeof body !== "string") {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  return proxy(() =>
    apiFetch(`/chat/rooms/${encodeURIComponent(slug)}`, {
      method: "POST",
      accessToken: token,
      body: { body },
    }),
  );
}
