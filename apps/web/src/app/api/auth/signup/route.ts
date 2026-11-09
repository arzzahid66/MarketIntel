import { NextResponse } from "next/server";

import { ApiError, apiFetch } from "@/lib/api";
import { ACCESS_COOKIE, ACCESS_MAX_AGE, REFRESH_COOKIE, REFRESH_MAX_AGE, cookieOptions } from "@/lib/session";

interface TokenPair {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

/** Kept in step with MIN_PASSWORD_LENGTH in apps/api/app/core/security.py. */
const MIN_PASSWORD_LENGTH = 10;

export async function POST(request: Request) {
  let payload: { email?: string; password?: string; display_name?: string };
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
  if (payload.password.length < MIN_PASSWORD_LENGTH) {
    return NextResponse.json(
      {
        error: "invalid_request",
        message: `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`,
      },
      { status: 400 },
    );
  }

  try {
    const tokens = await apiFetch<TokenPair>("/auth/signup", {
      method: "POST",
      body: {
        email: payload.email,
        password: payload.password,
        display_name: payload.display_name || null,
      },
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
      if (error.status === 409) {
        return NextResponse.json(
          { error: "email_taken", message: "That email cannot be registered." },
          { status: 409 },
        );
      }
      if (error.status === 422) {
        return NextResponse.json(
          { error: "invalid_request", message: "Check the email and password and try again." },
          { status: 400 },
        );
      }
    }
    return NextResponse.json(
      { error: "upstream_unavailable", message: "The service is unavailable. Try again shortly." },
      { status: 502 },
    );
  }
}
