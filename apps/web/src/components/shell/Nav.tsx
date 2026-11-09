import Link from "next/link";

import { LogoutButton } from "@/components/shell/LogoutButton";
import { ThemeToggle } from "@/components/shell/ThemeToggle";
import type { ThemePreference } from "@/lib/theme";
import type { Session } from "@/lib/types";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/markets", label: "Markets" },
  { href: "/analyst", label: "AI analyst" },
  { href: "/chat", label: "Chat" },
  { href: "/pricing", label: "Pricing" },
];

export function Nav({
  session,
  theme,
}: {
  session: Session | null;
  theme: ThemePreference;
}) {
  return (
    <header className="border-b border-line bg-surface">
      <nav
        aria-label="Main"
        className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4 sm:px-6"
      >
        <Link href="/" className="font-semibold tracking-tight text-ink no-underline">
          Market<span className="text-action">Intel</span>
        </Link>

        <ul className="hidden items-center gap-5 sm:flex">
          {LINKS.map((link) => (
            <li key={link.href}>
              <Link href={link.href} className="text-small text-muted no-underline hover:text-ink">
                {link.label}
              </Link>
            </li>
          ))}
        </ul>

        <div className="ml-auto flex items-center gap-3">
          <ThemeToggle current={theme} />
          {session ? (
            <>
              {/* The plan is a quiet label, not a badge. Colour means direction. */}
              <span className="hidden text-small text-muted sm:inline">
                {session.entitlements.plan_name}
              </span>
              <Link
                href="/dashboard"
                className="text-small text-muted no-underline hover:text-ink"
              >
                {session.user.display_name || session.user.email}
              </Link>
              <LogoutButton />
            </>
          ) : (
            <>
              <Link href="/login" className="text-small text-muted no-underline hover:text-ink">
                Log in
              </Link>
              <Link
                href="/signup"
                className="inline-flex h-8 items-center rounded-[var(--radius-ui)] border border-action bg-action px-3 text-small font-medium text-white no-underline hover:opacity-90 hover:no-underline"
              >
                Sign up
              </Link>
            </>
          )}
        </div>
      </nav>
    </header>
  );
}
