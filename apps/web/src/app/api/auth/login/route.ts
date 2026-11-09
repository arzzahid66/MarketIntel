/**
 * Exchanges credentials for httpOnly cookies.
 *
 * The browser posts here, not to FastAPI, so the tokens never enter JS.
 */

import { NextResponse } from "next/server";

import { ApiError, apiFetch } from "@/lib/api";
import { ACCESS_COOKIE, ACCESS_MAX_AGE, REFRESH_COOKIE, REFRESH_MAX_AGE, cookieOptions } from "@/lib/session";

interface TokenPair {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export async function POST(request: Request) {
  let payload: { email?: string; password?: string };
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_request" }, { status: 400 });
  }

  if (!payload.email || !payload.password) {
    return NextResponse.json(
      { error: "invalid_request", message: "Email and password are required." },
      { status: 400 },
    );
  }

  try {
    const tokens = await apiFetch<TokenPair>("/auth/login", {
      method: "POST",
      body: { email: payload.email, password: payload.password },
    });

    const response = NextResponse.json({ ok: true });
    response.cookies.set(ACCESS_COOKIE, tokens.access_token, {
      ...cookieOptions,
      maxAge: tokens.expires_in || ACCESS_MAX_AGE,
    });
    response.cookies.set(REFRESH_COOKIE, tokens.refresh_token, {
      ...cookieOptions,
      maxAge: REFRESH_MAX_AGE,
    });
    return response;
  } catch (error) {
    if (error instanceof ApiError) {
      // Pass the API's wording through unchanged so login stays a non-oracle.
      return NextResponse.json(
        { error: "login_failed", message: "Incorrect email or password." },
        { status: error.status === 401 ? 401 : 502 },
      );
    }
    return NextResponse.json(
      { error: "upstream_unavailable", message: "The service is unavailable. Try again shortly." },
      { status: 502 },
    );
  }
}
