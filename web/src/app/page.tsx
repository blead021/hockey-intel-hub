// Landing page (CLAUDE.md section 2): what PuckSleuth does, the tools, and the plans.
import Link from "next/link";
import { FREE_INCLUDES, PRO_INCLUDES } from "@/lib/plans";
import { SITE_NAME } from "@/lib/site";

const TOOLS = [
  { href: "/league", title: "League overview", pro: false,
    text: "Every team's needs and strengths graded against the league, with cap space, the top trade targets, and the most undervalued players." },
  { href: "/teams", title: "Team rosters", pro: false,
    text: "Contracts, cap by season, 5v5 results, Game Score, WAR, and who on the roster is better than fans think. Free for your favorite team." },
  { href: "/teams", title: "Player profiles", pro: true,
    text: "Play style, advanced metrics with percentiles, recent Game Scores, surplus value, the age curve, and contract by season." },
  { href: "/trade-targets", title: "Trade Targets", pro: true,
    text: "Who fits your team's needs and cap, which teams are likely sellers, and buy-low signals from underlying play." },
  { href: "/trade-builder", title: "Trade Builder", pro: true,
    text: "Build a deal, see the cap impact for both teams, retention, no-trade checks, and comparable past trades." },
  { href: "/rumors", title: "Rumor Tracker", pro: true,
    text: "Who the trade talk is about, whether it is rising or fading, and what fans and beat writers think." },
];

export default function Home() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-12">
      <div className="flex flex-col-reverse items-center gap-8 md:flex-row md:justify-between">
        <div className="text-center md:text-left">
          <p className="text-sm font-semibold uppercase tracking-widest text-muted">Front office tools for hockey fans</p>
          <h1 className="font-heading text-6xl font-bold uppercase tracking-tight sm:text-7xl">{SITE_NAME}</h1>
          <p className="mt-4 max-w-xl text-lg text-muted">
            Stats, Analytics, and Sentiment to help find the hidden gems around the league.
          </p>
          <div className="mt-6 flex flex-wrap justify-center gap-3 md:justify-start">
            <Link href="/league" className="rounded-md bg-ink px-5 py-2.5 font-semibold text-surface hover:bg-ink/90">Explore the league</Link>
            <Link href="/pricing" className="rounded-md border border-border px-5 py-2.5 font-semibold hover:border-ink">See plans</Link>
          </div>
        </div>
        {/* The hockey detective. Plain img: Cloudflare image resizing is off to avoid its fees. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/logo-large.webp"
          alt="PuckSleuth's hockey detective studying a puck through a magnifying glass"
          width={360}
          height={360}
          className="h-64 w-64 shrink-0 rounded-2xl border border-border shadow-sm sm:h-80 sm:w-80 md:h-[22rem] md:w-[22rem]"
        />
      </div>

      <h2 className="mt-14 font-heading text-3xl font-semibold uppercase tracking-tight">The tools</h2>
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {TOOLS.map((t) => (
          <Link key={t.title} href={t.href} className="rounded-lg border border-border bg-surface p-5 hover:border-ink">
            <div className="flex items-baseline justify-between gap-2">
              <h3 className="font-heading text-2xl font-semibold uppercase">{t.title}</h3>
              <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${t.pro ? "bg-positive-soft text-positive" : "bg-border-soft text-muted"}`}>
                {t.pro ? "Pro" : "Free"}
              </span>
            </div>
            <p className="mt-2 text-sm text-muted">{t.text}</p>
          </Link>
        ))}
      </div>

      <h2 className="mt-14 font-heading text-3xl font-semibold uppercase tracking-tight">Plans</h2>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-border bg-surface p-5">
          <h3 className="font-heading text-2xl font-semibold uppercase">Free</h3>
          <ul className="mt-3 space-y-1.5 text-sm">{FREE_INCLUDES.map((f) => <li key={f}>✓ {f}</li>)}</ul>
        </div>
        <div className="rounded-lg border-2 border-ink bg-surface p-5">
          <h3 className="font-heading text-2xl font-semibold uppercase">Pro</h3>
          <ul className="mt-3 space-y-1.5 text-sm">{PRO_INCLUDES.map((f) => <li key={f}>✓ {f}</li>)}</ul>
          <Link href="/pricing" className="mt-4 inline-block rounded-md bg-ink px-4 py-2 text-sm font-semibold text-surface">See pricing</Link>
        </div>
      </div>
    </main>
  );
}
