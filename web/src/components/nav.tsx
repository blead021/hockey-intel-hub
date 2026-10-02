"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { SITE_NAME } from "@/lib/site";

// The five core screens from the Design/ screenshots plus the Rumor Tracker. Screens not built yet are shown but not linked.
const TABS: { label: string; href: string | null; match: (path: string) => boolean }[] = [
  { label: "League", href: "/league", match: (p) => p.startsWith("/league") },
  { label: "Team Roster", href: "/teams", match: (p) => p.startsWith("/team") },
  { label: "Player Profile", href: null, match: (p) => p.startsWith("/player") },
  { label: "Trade Targets", href: null, match: (p) => p.startsWith("/trade-targets") },
  { label: "Trade Builder", href: null, match: (p) => p.startsWith("/trade-builder") },
  { label: "Rumor Tracker", href: "/rumors", match: (p) => p.startsWith("/rumors") },
];

export function SiteNav() {
  const path = usePathname() ?? "/";
  return (
    <header className="bg-ink text-surface">
      <div className="mx-auto flex max-w-7xl items-center gap-6 overflow-x-auto px-4 py-3">
        <Link href="/" className="shrink-0 font-heading text-2xl font-bold uppercase tracking-wide">
          {SITE_NAME}
        </Link>
        <nav className="flex shrink-0 gap-1 text-sm">
          {TABS.map((tab) => {
            const active = tab.match(path);
            const classes = `rounded-md px-3 py-2 ${active ? "bg-white/15 font-semibold" : "text-surface/80"}`;
            return tab.href ? (
              <Link key={tab.label} href={tab.href} className={`${classes} hover:bg-white/10`}>
                {tab.label}
              </Link>
            ) : (
              <span key={tab.label} className={`${classes} cursor-default ${active ? "" : "text-surface/40"}`} title="Coming soon">
                {tab.label}
              </span>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
