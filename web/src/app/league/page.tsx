import Link from "next/link";
import { connection } from "next/server";
import { Label, Panel, Unavailable } from "@/components/ui";
import { withDb } from "@/lib/db";
import { money, shortDate } from "@/lib/format";
import { availability, NEED_LABELS, unlikelyAvailable } from "@/lib/needs";
import { getLeagueGrid, getTradeTargets, getUndervalued, type LeagueRow, type TradeTarget, type Undervalued } from "@/lib/queries";
import { currentSeason } from "@/lib/seasons";

export const metadata = { title: "League overview" };

// Grid columns in the Design/ screenshot order. Prospect depth is left out (Brian, 2026-10-03): no data source grades it.
const COLUMNS: { key: string; label: string; name: string }[] = [
  { key: "goal_scoring", label: "Goals", name: "Goal scoring" },
  { key: "playmaking", label: "Creation", name: "Playmaking" },
  { key: "physicality", label: "Physical", name: "Physicality" },
  { key: "defense_5v5", label: "5v5 D", name: "5v5 defense" },
  { key: "power_play", label: "PP", name: "Power play" },
  { key: "penalty_kill", label: "PK", name: "Penalty kill" },
  { key: "goaltending", label: "Goalie", name: "Goaltending" },
];

const GRADES: Record<number, { label: string; cls: string }> = {
  [-2]: { label: "Need", cls: "bg-negative text-surface" },
  [-1]: { label: "Thin", cls: "bg-negative-soft text-negative" },
  0: { label: "", cls: "bg-border-soft" },
  1: { label: "Solid", cls: "bg-positive-soft text-positive" },
  2: { label: "Strong", cls: "bg-positive text-surface" },
};

const BIG_SPACE = 8_000_000;

export default async function LeaguePage({ searchParams }: PageProps<"/league">) {
  await connection();
  const conf = (await searchParams).conf;
  const conference = conf === "Eastern" || conf === "Western" ? conf : undefined;
  const season = currentSeason();
  const { grid, targets, undervalued } = await withDb(async (sql) => {
    const [grid, targets, undervalued] = await Promise.all([
      getLeagueGrid(sql, season), getTradeTargets(sql, season, {}), getUndervalued(sql, season, null, 10),
    ]);
    return { grid, targets, undervalued };
  });
  const { rows: all, asOf, sample } = grid;
  // Top 10 trade targets: most trade chatter, weighted by how likely his team is to deal him; contenders' core left out.
  const topTargets = targets
    .filter((t) => t.chatter > 0 && !unlikelyAvailable(t))
    .sort((a, b) => b.chatter * availability(b) - a.chatter * availability(a) || (b.war_proj ?? -9) - (a.war_proj ?? -9))
    .slice(0, 10);
  const rows = conference ? all.filter((r) => r.conference === conference) : all;

  // Summary cards count across the teams shown.
  const counts = COLUMNS.map((c) => ({
    ...c,
    weak: rows.filter((r) => (r.grades[c.key] ?? 0) < 0).length,
    strong: rows.filter((r) => (r.grades[c.key] ?? 0) > 0).length,
  }));
  const byNeed = [...counts].sort((a, b) => b.weak - a.weak);
  const deepest = [...counts].sort((a, b) => b.strong - a.strong)[0];
  const buyers = rows.filter((r) => (r.cap_space ?? 0) >= BIG_SPACE).length;

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-widest text-muted">
            {conference ? `${conference} Conference` : "All 32 teams"} · {asOf ? `updated ${shortDate(asOf)}` : "not graded yet"}
          </p>
          <h1 className="font-heading text-4xl font-bold uppercase leading-tight tracking-tight sm:text-5xl">League overview</h1>
        </div>
        <nav className="flex gap-2">
          {[undefined, "Eastern", "Western"].map((c) => (
            <Link
              key={c ?? "all"}
              href={c ? `/league?conf=${c}` : "/league"}
              className={`rounded-full border px-4 py-2 text-sm font-semibold ${conference === c ? "border-ink bg-ink text-surface" : "border-border bg-surface"}`}
            >
              {c ?? "All teams"}
            </Link>
          ))}
        </nav>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Summary label="Most common need" value={byNeed[0]?.name} tone="negative" detail={`${byNeed[0]?.weak ?? 0} teams graded Need or Thin`} />
        <Summary label="Second most common need" value={byNeed[1]?.name} tone="negative" detail={`${byNeed[1]?.weak ?? 0} teams graded Need or Thin`} />
        <Summary label="Deepest league-wide" value={deepest?.name} tone="positive" detail={`${deepest?.strong ?? 0} teams graded Solid or Strong`} />
        <Summary label={`Teams with ${money(BIG_SPACE)}+ space`} value={String(buyers)} detail="Buyers with room to absorb a contract" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Panel title="Team needs & strengths" note="Built from each roster's results">
          <div className="overflow-x-auto">
            <table className="w-full min-w-max border-separate border-spacing-1 text-sm">
              <thead>
                <tr className="text-xs font-semibold uppercase tracking-wide text-muted">
                  <th className="pr-2 text-left">Team</th>
                  {COLUMNS.map((c, i) => (
                    <th key={c.key} className="px-1 text-center">
                      <Label text={c.label} term={`${c.label} (grade)`} align={i >= COLUMNS.length / 2 ? "right" : "left"} />
                    </th>
                  ))}
                  <th className="pl-2 text-right"><Label text="Space" align="right" /></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => <GridRow key={r.team_id} r={r} />)}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex flex-wrap gap-3 text-xs">
            {[-2, -1, 0, 1, 2].map((g) => (
              <span key={g} className="flex items-center gap-1">
                <span className={`inline-block h-3 w-3 rounded-sm ${GRADES[g].cls}`} />
                {GRADES[g].label || "Average"}
              </span>
            ))}
          </div>
          <p className="mt-3 text-xs text-muted">
            Goals: goals for per game. Creation: primary assists per game. Physical: hits and blocked shots per game.
            5v5 D: expected goals against per 60 at 5v5. PP and PK: NHL power play and penalty kill percentages.
            Goalie: goals saved above expected per game. Grades compare each team
            with the other 31{sample ? `, using the ${sample}` : ""}. Space is the cap ceiling minus NHL roster
            cap hits and retained salary.
          </p>
        </Panel>

        <div className="space-y-6">
          <Panel title="Top 10 trade targets" note="Ranked by trade chatter and availability">
            {topTargets.length === 0 ? <Unavailable>No trade chatter yet.</Unavailable> : (
              <TargetsTable rows={topTargets} grid={all} />
            )}
          </Panel>
          <Panel title="Top 10 undervalued" note="Performance percentile minus fan sentiment">
            {undervalued.length === 0 ? <Unavailable>Not enough fan sentiment yet.</Unavailable> : <UndervaluedTable rows={undervalued} />}
          </Panel>
        </div>
      </div>
    </main>
  );
}

function Summary({ label, value, detail, tone }: { label: string; value: string | undefined; detail: string; tone?: "positive" | "negative" }) {
  const color = tone === "negative" ? "text-negative" : tone === "positive" ? "text-positive" : "";
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted"><Label text={label} /></p>
      <p className={`mt-1 font-heading text-3xl font-semibold ${color}`}>{value ?? "—"}</p>
      <p className="mt-1 text-xs text-muted">{detail}</p>
    </div>
  );
}

function GridRow({ r }: { r: LeagueRow }) {
  return (
    <tr>
      <td className="pr-2 text-left">
        <Link href={`/team/${r.abbrev}`} className="hover:underline">{r.name}</Link>
      </td>
      {COLUMNS.map((c) => {
        const g = r.grades[c.key];
        const style = g == null ? { label: "", cls: "bg-border-soft/50" } : GRADES[g];
        return (
          <td key={c.key} className={`h-7 w-16 rounded text-center text-xs font-semibold ${style.cls}`} title={g == null ? "Not graded" : style.label || "Average"}>
            {style.label}
          </td>
        );
      })}
      <td className={`pl-2 text-right font-mono ${r.cap_space != null && r.cap_space < 0 ? "text-negative" : ""}`}>{money(r.cap_space)}</td>
    </tr>
  );
}

// Best fits (CLAUDE.md section 6): teams graded Need or Thin in his strongest category, with cap space for at least
// half his cap hit (the 50% retention limit), not his own team; most severe need first, then most cap space.
function bestFits(t: TradeTarget, grid: LeagueRow[]): { teams: string[]; category: string | null } {
  const strengths = Object.entries(t.need ?? {}).filter(([, v]) => v != null).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0));
  const category = strengths[0]?.[0] ?? null;
  if (!category) return { teams: [], category: null };
  const teams = grid
    .filter((r) => r.abbrev !== t.team && (r.grades[category] ?? 0) < 0 && (r.cap_space ?? 0) >= t.cap_hit * 0.5)
    .sort((a, b) => (a.grades[category] ?? 0) - (b.grades[category] ?? 0) || (b.cap_space ?? 0) - (a.cap_space ?? 0))
    .slice(0, 3)
    .map((r) => r.abbrev);
  return { teams, category };
}

function TargetsTable({ rows, grid }: { rows: TradeTarget[]; grid: LeagueRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-max border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-xs font-semibold uppercase tracking-wide text-muted">
            <th className="py-2 pr-2 text-left">#</th><th className="py-2 text-left">Player</th><th className="px-2 py-2 text-right"><Label text="Cap / yrs" align="right" /></th>
            <th className="px-2 py-2 text-right"><Label text="Chatter" align="right" /></th><th className="px-2 py-2 text-right"><Label text="Fans" align="right" /></th><th className="px-2 py-2 text-right"><Label text="Beat" align="right" /></th>
            <th className="py-2 pl-2 text-left"><Label text="Best fits" align="right" /></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t, i) => {
            const fits = bestFits(t, grid);
            return (
              <tr key={t.player_id} className="border-b border-border-soft align-top">
                <td className="py-2 pr-2 font-mono text-muted">{i + 1}</td>
                <td className="py-2">
                  <Link href={`/player/${t.player_id}`} className="font-semibold hover:underline">{t.name}</Link>
                  <p className="text-xs text-muted">{t.team} · {t.position} · age {t.age ?? "—"}</p>
                </td>
                <td className="px-2 py-2 text-right font-mono">{money(t.cap_hit)} / {t.years}</td>
                <td className="px-2 py-2 text-right font-mono text-negative">{t.chatter}</td>
                <td className="px-2 py-2 text-right font-mono">{t.fans == null ? "—" : Math.round(t.fans)}</td>
                <td className="px-2 py-2 text-right font-mono">{t.beat == null ? "—" : Math.round(t.beat)}</td>
                <td className="py-2 pl-2">
                  <p className="font-semibold">{fits.teams.length ? fits.teams.join(", ") : "—"}</p>
                  <p className="text-xs text-muted">{fits.category ? NEED_LABELS[fits.category] ?? fits.category : ""}</p>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-muted">
        Best fits = teams graded Need or Thin in the player&apos;s strongest area, with cap room for the deal at up to 50% retention.
      </p>
    </div>
  );
}

function UndervaluedTable({ rows }: { rows: Undervalued[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-max border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-xs font-semibold uppercase tracking-wide text-muted">
            <th className="py-2 pr-2 text-left">#</th><th className="py-2 text-left">Player</th><th className="px-2 py-2 text-right"><Label text="Cap" term="Cap hit" align="right" /></th>
            <th className="px-2 py-2 text-right"><Label text="Fans" align="right" /></th><th className="px-2 py-2 text-right"><Label text="Perf." align="right" /></th>
            <th className="px-2 py-2 text-left"><Label text="Perception gap" align="left" /></th><th className="py-2 pl-2 text-right"><Label text="Surplus" align="right" /></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((u, i) => (
            <tr key={u.player_id} className="border-b border-border-soft align-top">
              <td className="py-2 pr-2 font-mono text-muted">{i + 1}</td>
              <td className="max-w-xs py-2">
                <Link href={`/player/${u.player_id}`} className="font-semibold hover:underline">{u.name}</Link>
                <p className="text-xs text-muted">{u.team} · {u.position} · {u.age ?? "—"}{u.reason ? ` · ${u.reason}` : ""}</p>
              </td>
              <td className="px-2 py-2 text-right font-mono">{money(u.cap_hit)}</td>
              <td className="px-2 py-2 text-right font-mono text-negative">{Math.round(u.fans)}</td>
              <td className="px-2 py-2 text-right font-mono text-positive">{Math.round(u.perf_pct)}</td>
              <td className="px-2 py-2">
                <div className="flex items-center gap-2">
                  <div className="h-2 w-20 overflow-hidden rounded-full bg-border-soft" aria-hidden>
                    <div className="h-full bg-positive" style={{ width: `${Math.min(u.gap, 100)}%` }} />
                  </div>
                  <span className="font-mono text-xs">+{Math.round(u.gap)}</span>
                </div>
              </td>
              <td className={`py-2 pl-2 text-right font-mono ${u.surplus == null ? "" : u.surplus >= 0 ? "text-positive" : "text-negative"}`}>
                {u.surplus == null ? "—" : `${u.surplus >= 0 ? "+" : "−"}${money(Math.abs(u.surplus))}`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-muted">
        Perception gap = how his performance ranks at his position minus how his fans rate him, among players fans
        discuss. The league&apos;s biggest stars are left out. Reasons are written by Claude from the numbers only.
      </p>
    </div>
  );
}
