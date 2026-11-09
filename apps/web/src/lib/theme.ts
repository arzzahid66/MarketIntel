/**
 * Theme preference. A cookie, not `localStorage`.
 *
 * Two reasons, and the first is the one that matters:
 *
 *   1. **The server needs to know the theme before it renders.** A cookie
 *      arrives with the request, so `<html data-theme>` is correct in the first
 *      byte of HTML. `localStorage` is only readable after hydration, which is
 *      why sites that use it either flash white or inject a blocking script
 *      into `<head>`.
 *   2. `localStorage` is banned by an ESLint rule in this app, because session
 *      tokens live in httpOnly cookies and a stray client-side store would
 *      undermine that model.
 *
 * This cookie is deliberately *not* httpOnly: it carries no authority, and the
 * toggle reads the current value to decide what to switch to.
 */

export const THEME_COOKIE = "mip_theme";

/** `system` is represented by the absence of the cookie, never by a value. */
export type Theme = "light" | "dark";
export type ThemePreference = Theme | "system";

export const THEME_MAX_AGE = 60 * 60 * 24 * 365;

export function isTheme(value: string | undefined): value is Theme {
  return value === "light" || value === "dark";
}

/**
 * The value for `<html data-theme>`, or undefined to follow the OS.
 *
 * Returning undefined rather than a guessed "light" is the point: the CSS falls
 * through to `prefers-color-scheme`, so a reader who has never touched the
 * toggle gets whatever their machine is set to.
 */
export function themeAttribute(cookieValue: string | undefined): Theme | undefined {
  return isTheme(cookieValue) ? cookieValue : undefined;
}
