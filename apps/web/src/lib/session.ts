/**
 * Cookie-backed session.
 *
 * Tokens are httpOnly cookies, never localStorage, so an XSS bug cannot walk
 * off with a session. Only the Next.js server reads them, and only to forward
 * a Bearer header to FastAPI.
 *
 * When Clerk is switched on (AUTH_PROVIDER=clerk) Clerk's middleware replaces
 * the cookie plumbing here; `getSession()` stays the interface the pages use.
 */

import { cookies } from "next/headers";

import { apiFetch, ApiError } from "@/lib/api";
import type { Entitlements, Session } from "@/lib/types";

export const ACCESS_COOKIE = "mip_access";
export const REFRESH_COOKIE = "mip_refresh";

const isProduction = process.env.NODE_ENV === "production";

export const cookieOptions = {
  httpOnly: true,
  sameSite: "lax",
  secure: isProduction,
  path: "/",
} as const;

/** Access-token lifetime is short; the refresh cookie is what keeps a user in. */
export const ACCESS_MAX_AGE = 60 * 30;
export const REFRESH_MAX_AGE = 60 * 60 * 24 * 30;

/**
 * The signed-in user plus their entitlements, or null.
 *
 * Entitlements come from the API on every call, resolved from the subscriptions
 * table. Nothing is read out of the token, and nothing is cached across
 * requests - a downgrade must take effect on the very next page load.
 */
export async function getSession(): Promise<Session | null> {
  const store = await cookies();
  const token = store.get(ACCESS_COOKIE)?.value;
  if (!token) return null;

  try {
    return await apiFetch<Session>("/me", { accessToken: token });
  } catch (error) {
    if (error instanceof ApiError && error.isUnauthorized) return null;
    throw error;
  }
}

/** Entitlements for whoever is asking, signed in or not. Free tier when not. */
export async function getEntitlements(): Promise<Entitlements | null> {
  const store = await cookies();
  const token = store.get(ACCESS_COOKIE)?.value;
  try {
    return await apiFetch<Entitlements>("/entitlements", {
      ...(token ? { accessToken: token } : {}),
    });
  } catch {
    return null;
  }
}

export async function getAccessToken(): Promise<string | undefined> {
  const store = await cookies();
  return store.get(ACCESS_COOKIE)?.value;
}
