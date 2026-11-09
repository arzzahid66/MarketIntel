/**
 * Route guard + silent token refresh.
 *
 * Next.js 16 renamed the `middleware` file convention to `proxy`; this file was
 * src/middleware.ts in Phase 1. Proxy runs on the Node.js runtime by default.
 *
 * Proxy is the only place that can both read cookies and set them on the
 * way out, so it is where a short-lived access token gets renewed from the
 * refresh cookie. Server components then just read a valid cookie.
 *
 * This is intentionally the *only* client-side notion of "logged in". It is a
 * redirect convenience, not a security boundary - the API authorises every call.
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { ACCESS_COOKIE, ACCESS_MAX_AGE, REFRESH_COOKIE, REFRESH_MAX_AGE, cookieOptions } from "@/lib/session";

const PROTECTED_PREFIXES = ["/dashboard", "/account"];
const AUTH_PAGES = ["/login", "/signup"];

/** Renew this many seconds before expiry so a request never races the clock. */
const REFRESH_SKEW_SECONDS = 60;

function isExpiringSoon(token: string): boolean {
  // Reads `exp` without verifying the signature. Safe: the API verifies for
  // real, and a forged token just fails there. This only decides *when to try*.
  const segment = token.split(".")[1];
  if (!segment) return true;
  try {
    const json = atob(segment.replace(/-/g, "+").replace(/_/g, "/"));
    const claims = JSON.parse(json) as { exp?: number };
    if (typeof claims.exp !== "number") return true;
    return claims.exp - Math.floor(Date.now() / 1000) < REFRESH_SKEW_SECONDS;
  } catch {
    return true;
  }
}

async function refreshTokens(
  refreshToken: string,
): Promise<{ access: string; refresh: string; expiresIn: number } | null> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(`${apiUrl}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
    });
    if (!response.ok) return null;
    const tokens = (await response.json()) as {
      access_token: string;
      refresh_token: string;
      expires_in: number;
    };
    return {
      access: tokens.access_token,
      refresh: tokens.refresh_token,
      expiresIn: tokens.expires_in,
    };
  } catch {
    // API unreachable. Fall through and let the page render its degraded state
    // rather than bouncing the user to /login on a transient blip.
    return null;
  }
}

export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  const access = request.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;

  let effectiveAccess = access;
  let renewed: { access: string; refresh: string; expiresIn: number } | null = null;

  if (refresh && (!access || isExpiringSoon(access))) {
    renewed = await refreshTokens(refresh);
    if (renewed) effectiveAccess = renewed.access;
  }

  const signedIn = Boolean(effectiveAccess);
  const isProtected = PROTECTED_PREFIXES.some((p) => pathname.startsWith(p));
  const isAuthPage = AUTH_PAGES.includes(pathname);

  let response: NextResponse;

  if (isProtected && !signedIn) {
    const login = request.nextUrl.clone();
    login.pathname = "/login";
    login.search = `?next=${encodeURIComponent(pathname + search)}`;
    response = NextResponse.redirect(login);
  } else if (isAuthPage && signedIn) {
    const dashboard = request.nextUrl.clone();
    dashboard.pathname = "/dashboard";
    dashboard.search = "";
    response = NextResponse.redirect(dashboard);
  } else {
    response = NextResponse.next();
  }

  if (renewed) {
    response.cookies.set(ACCESS_COOKIE, renewed.access, {
      ...cookieOptions,
      maxAge: renewed.expiresIn || ACCESS_MAX_AGE,
    });
    response.cookies.set(REFRESH_COOKIE, renewed.refresh, {
      ...cookieOptions,
      maxAge: REFRESH_MAX_AGE,
    });
  } else if (refresh && !signedIn) {
    // Refresh token is dead. Clear it so we stop retrying on every request.
    response.cookies.set(REFRESH_COOKIE, "", { ...cookieOptions, maxAge: 0 });
  }

  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/).*)"],
};
