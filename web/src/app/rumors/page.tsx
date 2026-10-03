import { Locked } from "@/components/locked";
import { can } from "@/lib/access";
import { currentAccess } from "@/lib/session";
import Link from "next/link";
import { connection } from "next/server";
import { Label, Panel, Unavailable } from "@/components/ui";
import { withDb } from "@/lib/db";
import { money, season as seasonLabel, shortDate } from "@/lib/format";
import { getEnabledSources, getRumors, getTeams, type Rumor } from "@/lib/queries";

export const metadata = { title: "Rumor Tracker" };

const GROUPS = [
  { key: undefined, label: "All" },
  { key: "F", label: "Forwards" },
  { key: "D", label: "Defense" },
  { key: "G", label: "Goalies" },
] as const;

const AUDIENCES: Record<string, string> = { fan: "Fans", beat_writer: "Beat writer", media: "Media" };

export default async function RumorsPage({ searchParams }: PageProps<"/rumors">) {
  await connection();
  if (!can(await withDb(currentAccess), "rumors")) return <Locked eyebrow="Pro" title="Rumor Tracker" what="the Rumor Tracker" />;
  const params = await searchParams;
  const team = typeof params.team === "string" && /^[A-Z]{3}$/.test(params.team) ? params.team : undefined;
  const group = params.pos === "F" || params.pos === "D" || params.pos === "G" ? params.pos : undefined;

  const { rumors, teams, scoring } = await withDb(async (sql) => {
    const [rumors, teams, sources] = await Promise.all([getRumors(sql, { team, group }), getTeams(sql), getEnabledSources(sql)]);
    return { rumors, teams, scoring: sources.has("sentiment_scoring") };
  });

  const href = (next: { team?: string; pos?: string }) => {
    const q = new URLSearchParams();
    const t = "team" in next ? next.team : team;
    const p = "pos" in next ? next.pos : group;
    if (t) q.set("team", t);
    if (p) q.set("pos", p);
    const s = q.toString();
    return s ? `/rumors?${s}` : "/rumors";
  };

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-8">
      <div>
        <p className="text-sm font-semibold uppercase tracking-widest text-muted">League-wide · trade mentions in the last 7 days</p>
        <h1 className="font-heading text-4xl font-bold uppercase leading-tight tracking-tight sm:text-5xl">Rumor tracker</h1>
      </div>

      <section className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface p-4">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted">Filters</span>
        {GROUPS.map((g) => (
          <Link
            key={g.label}
            href={href({ pos: g.key })}
            className={`rounded-full border px-4 py-1.5 text-sm font-semibold ${group === g.key ? "border-ink bg-ink text-surface" : "border-border"}`}
          >
            {g.label}
          </Link>
        ))}
        <form action="/rumors" className="ml-auto flex items-center gap-2">
          {group && <input type="hidden" name="pos" value={group} />}
          <select name="team" defaultValue={team ?? ""} className="rounded-md border border-border bg-surface px-3 py-1.5 text-sm">
            <option value="">All teams</option>
            {teams.map((t) => <option key={t.abbrev} value={t.abbrev}>{t.name}</option>)}
          </select>
          <button className="rounded-md border border-border px-3 py-1.5 text-sm font-semibold">Apply</button>
        </form>
      </section>

      {rumors.length === 0 ? (
        <Panel title="No trade chatter yet">
          <Unavailable>
            {scoring
              ? "No player has trade mentions in the last 7 days for this filter."
              : "Trade chatter appears once sentiment scoring is switched on. Posts and headlines are already being collected, so the tracker fills in from the start of collection."}
          </Unavailable>
        </Panel>
      ) : (
        <div className="space-y-4">
          {rumors.map((r) => <RumorCard key={r.player_id} r={r} />)}
        </div>
      )}

      <p className="text-xs text-muted">
        Chatter = trade-related mentions in the last 7 days across Bluesky, YouTube, and news headlines. Rising or fading
        compares the last 7 days with the 7 before and appears after 14 days of history; a spike (twice the usual weekly
        level) appears after 35 days. Summaries are written by us; follow the links for the original
        sources.
      </p>
    </main>
  );
}

function RumorCard({ r }: { r: Rumor }) {
  // Rising or fading compares two weeks, so it needs 14 days of history.
  const trend = r.history_days < 14 ? null : r.chatter_7d > r.prior_7d ? "rising" : "fading";
  const top = Math.max(...r.daily, 1);
  return (
    <section className="grid gap-4 rounded-lg border border-border bg-surface p-5 md:grid-cols-[minmax(0,16rem)_minmax(0,1fr)_minmax(0,18rem)]">
      <div>
        <Link href={`/player/${r.player_id}`} className="font-heading text-2xl font-semibold hover:underline">{r.name}</Link>
        <p className="text-sm text-muted">
          {[r.team, r.position, r.age != null ? `age ${r.age}` : null].filter(Boolean).join(" · ")}
        </p>
        {r.cap_hit != null && (
          <p className="mt-1 font-mono text-sm">
            {money(r.cap_hit)}
            {r.end_season ? ` · through ${seasonLabel(r.end_season)}` : ""}
            {r.expiry_status ? `, ${r.expiry_status}` : ""}
          </p>
        )}
        <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold">
          {trend && (
            <span className={`rounded-full px-2 py-1 ${trend === "rising" ? "bg-negative-soft text-negative" : "bg-border-soft text-muted"}`}>
              {trend === "rising" ? "▲ Rising" : "▼ Fading"}
            </span>
          )}
          {r.spike && <span className="rounded-full bg-negative-soft px-2 py-1 text-negative">Spike</span>}
        </div>
      </div>

      <div>
        <div className="flex items-baseline justify-between">
          <p className="text-sm font-semibold">Trade chatter, last 14 days</p>
          <p className="font-mono text-sm text-negative">
            {r.history_days >= 14 ? `${r.prior_7d} → ${r.chatter_7d} per week` : `${r.chatter_7d} this week`}
          </p>
        </div>
        <div className="mt-2 flex h-14 items-end gap-1" aria-label={`Daily trade mentions: ${r.daily.join(", ")}`}>
          {r.daily.map((n, i) => (
            <div key={i} className={`flex-1 rounded-sm ${i >= 7 ? "bg-negative" : "bg-border"}`} style={{ height: `${Math.max((n / top) * 100, 4)}%` }} />
          ))}
        </div>
        <div className="mt-3 grid grid-cols-3 gap-2 text-center">
          {[["Fans", r.fans], ["Beat", r.beat], ["Media", r.media]].map(([label, v]) => (
            <div key={label as string} className="rounded-md border border-border p-2">
              <p className="text-xs text-muted"><Label text={label as string} align={label === "Media" ? "right" : "left"} /></p>
              <p className="font-mono">{v == null ? "—" : Math.round(v as number)}</p>
            </div>
          ))}
        </div>
      </div>

      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Latest</p>
        {r.mentions.length === 0 ? (
          <p className="text-sm text-muted">No summaries yet.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {r.mentions.map((m, i) => (
              <li key={i}>
                <span className="font-semibold text-positive">{AUDIENCES[m.audience] ?? m.audience}</span>{" "}
                <span className="text-xs text-muted">{shortDate(m.posted_at)}</span>
                <br />
                {m.url ? <a href={m.url} target="_blank" rel="noopener noreferrer" className="hover:underline">{m.summary}</a> : m.summary}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
