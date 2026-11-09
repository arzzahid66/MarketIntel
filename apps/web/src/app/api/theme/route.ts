/**
 * Stores the viewer's theme choice.
 *
 * A route handler rather than a client-side write, so the cookie is set with
 * the same attributes as every other cookie this app sets, and the next server
 * render already knows the answer.
 */

import { NextResponse } from "next/server";

import { THEME_COOKIE, THEME_MAX_AGE, isTheme } from "@/lib/theme";

export async function POST(request: Request) {
  let theme: unknown;
  try {
    ({ theme } = await request.json());
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  if (theme === "system") {
    const response = NextResponse.json({ theme: "system" });
    // Absence of the cookie *is* "follow the OS", so clearing it is the write.
    response.cookies.delete(THEME_COOKIE);
    return response;
  }

  if (typeof theme !== "string" || !isTheme(theme)) {
    return NextResponse.json({ error: "unknown_theme" }, { status: 400 });
  }

  const response = NextResponse.json({ theme });
  response.cookies.set(THEME_COOKIE, theme, {
    path: "/",
    maxAge: THEME_MAX_AGE,
    sameSite: "lax",
    // Not httpOnly on purpose: the toggle is a client component that reads the
    // current choice. The cookie grants nothing.
    httpOnly: false,
  });
  return response;
}
