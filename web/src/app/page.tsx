// Interim home page until the landing page with pricing is built in Phase 6.
import Link from "next/link";
import { SITE_NAME } from "@/lib/site";

const LINKS = [
  { href: "/league", title: "League overview", text: "Every team's needs and surpluses, graded against the league, with cap space." },
  { href: "/teams", title: "Team rosters", text: "Contracts, 5v5 results, Game Score, and the reserve list for all 32 teams." },
  { href: "/rumors", title: "Rumor tracker", text: "Who the trade talk is about, whether it is rising or fading, and what fans think." },
];

export default function Home() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-16">
      <p className="text-sm font-semibold uppercase tracking-widest text-muted">Front office tools for hockey fans</p>
      <h1 className="font-heading text-5xl font-bold uppercase tracking-tight sm:text-6xl">{SITE_NAME}</h1>
      <p className="mt-4 max-w-2xl text-lg text-muted">
        Player stats, advanced analytics, expected goals, contracts, and what fans and beat writers are saying, all in
        one place. Updated after every night of games.
      </p>
      <div className="mt-10 grid gap-4 sm:grid-cols-3">
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} className="rounded-lg border border-border bg-surface p-5 hover:border-ink">
            <h2 className="font-heading text-2xl font-semibold uppercase">{l.title}</h2>
            <p className="mt-2 text-sm text-muted">{l.text}</p>
          </Link>
        ))}
      </div>
      <p className="mt-10 text-xs text-muted">
        Early preview. More tools, including Trade Targets and the Trade Builder, are on the way.
      </p>
    </main>
  );
}
