import Link from "next/link";
import { SITE_NAME } from "@/lib/site";

const LINKS = [
  { href: "/pricing", label: "Pricing" },
  { href: "/account", label: "Account" },
  { href: "/contact", label: "Contact" },
  { href: "/terms", label: "Terms" },
  { href: "/privacy", label: "Privacy" },
];

export function SiteFooter() {
  return (
    <footer className="mt-16 border-t border-border">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-6 text-sm text-muted">
        <p>
          {SITE_NAME} · Not affiliated with the NHL or any of its teams.
        </p>
        <nav className="flex flex-wrap gap-4">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className="hover:text-ink">{l.label}</Link>
          ))}
        </nav>
      </div>
    </footer>
  );
}
