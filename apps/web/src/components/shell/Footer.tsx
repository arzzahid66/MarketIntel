import Link from "next/link";

import { Disclaimer } from "@/components/shell/Disclaimer";

/**
 * Terms, Privacy and cookie consent are Phase 5 blockers, not optional extras.
 * The links exist now and point at placeholder pages so the footer's shape is
 * fixed and nothing has to be redesigned around them later.
 */
const LEGAL = [
  { href: "/legal/terms", label: "Terms" },
  { href: "/legal/privacy", label: "Privacy" },
];

export function Footer({ apiVersion }: { apiVersion?: string }) {
  return (
    <footer className="mt-12 border-t border-line bg-surface">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-6 sm:px-6">
        <Disclaimer />
        <div className="flex flex-wrap items-center gap-4 text-small text-muted">
          <span>© {new Date().getFullYear()} MarketIntel</span>
          {LEGAL.map((item) => (
            <Link key={item.href} href={item.href} className="text-muted no-underline hover:text-ink">
              {item.label}
            </Link>
          ))}
          {apiVersion && <span className="ml-auto tnum">API v{apiVersion}</span>}
        </div>
      </div>
    </footer>
  );
}
