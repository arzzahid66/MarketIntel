import type { Metadata } from "next";
import { IBM_Plex_Mono, Public_Sans } from "next/font/google";
import { cookies } from "next/headers";

import { Footer } from "@/components/shell/Footer";
import { Nav } from "@/components/shell/Nav";
import { apiFetchOrNull } from "@/lib/api";
import { getSession } from "@/lib/session";
import { THEME_COOKIE, themeAttribute } from "@/lib/theme";
import type { HealthResponse } from "@/lib/types";

import "./globals.css";

/**
 * Two families, that is the budget (section 6 rule 3): one grotesque for UI
 * text, one mono for figures.
 */
const publicSans = Public_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-public-sans",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
  variable: "--font-plex-mono",
});

export const metadata: Metadata = {
  title: {
    default: "MarketIntel — market intelligence dashboard",
    template: "%s · MarketIntel",
  },
  description:
    "Big 7 ticker dashboard with directional signals, a categorised news and social feed, and an AI analyst.",
  robots: { index: true, follow: true },
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // The shell renders even when the API is unreachable; each surface shows its
  // own degraded state instead of the whole page erroring.
  const [session, health, jar] = await Promise.all([
    getSession().catch(() => null),
    apiFetchOrNull<HealthResponse>("/health"),
    cookies(),
  ]);

  // Resolved here, on the server, so the first paint is already the right
  // theme. No blocking script in <head>, no flash of the wrong palette.
  const theme = themeAttribute(jar.get(THEME_COOKIE)?.value);

  return (
    <html
      lang="en"
      {...(theme ? { "data-theme": theme } : {})}
      className={`${publicSans.variable} ${plexMono.variable}`}
    >
      <body className="flex min-h-screen flex-col">
        <Nav session={session} theme={theme ?? "system"} />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">{children}</main>
        <Footer apiVersion={health?.version} />
      </body>
    </html>
  );
}
