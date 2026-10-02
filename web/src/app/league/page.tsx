import Link from "next/link";
import { connection } from "next/server";
import { Panel, Unavailable } from "@/components/ui";
import { withDb } from "@/lib/db";
import { money, shortDate } from "@/lib/format";
import { getLeagueGrid, type LeagueRow } from "@/lib/queries";
import { currentSeason } from "@/lib/seasons";

export const metadata = { title: "League overview" };

// Grid columns in the Design/ screenshot order. Prospect depth has no data source yet.
const COLUMNS: { key: string; label: string; name: string }[] = [
  { key: "goal_scoring", label: "Goals", name: "Goal scoring" },
  { key: "playmaking", label: "Creation", name: "Playmaking" },
  { key: "physicality", label: "Physical", name: "Physicality" },
  { key: "defense_5v5", label: "5v5 D", name: "5v5 defense" },
  { key: "power_play", label: "PP", name: "Power play" },
  { key: "penalty_kill", label: "PK", name: "Penalty kill" },
  { key: "goaltending", label: "Goalie", name: "Goaltending" },
  { key: "prospects", label: "Prospects", name: "Prospect depth" },
];

const GRADES: Record<number, { label: string; cls: string }> = {
  [-2]: { label: "Need", cls: "bg-negative text-surface" },
  [-1]: { label: "Thin", cls: "bg-negative-soft text-negative" },
  0: { label: "", cls: "bg-border-soft" },
  1: { label: "Solid", cls: "bg-positive-soft text-positive" },
  2: { label: "Surplus", cls: "bg-positive text-surface" },
};

const BIG_SPACE = 8_000_000;

export default async function LeaguePage({ searchParams }: PageProps<"/league">) {
  await connection();
  const conf = (await searchParams).conf;
  const conference = conf === "Eastern" || conf === "Western" ? conf : undefined;
  const { rows: all, asOf, sample } = await withDb((sql) => getLeagueGrid(sql, currentSeason()));
  const rows = conference ? all.filter((r) => r.conference === conference) : all;

  // Summary cards count across the teams shown.
  const counts = COLUMNS.filter((c) => c.key !== "prospects").map((c) => ({
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
        <Summary label="Deepest league-wide" value={deepest?.name} tone="positive" detail={`${deepest?.strong ?? 0} teams graded Solid or Surplus`} />
        <Summary label={`Teams with ${money(BIG_SPACE)}+ space`} value={String(buyers)} detail="Buyers with room to absorb a contract" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Panel title="Team needs & surpluses" note="Built from each roster's results">
          <div className="overflow-x-auto">
            <table className="w-full min-w-max border-separate border-spacing-1 text-sm">
              <thead>
                <tr className="text-xs font-semibold uppercase tracking-wide text-muted">
                  <th className="pr-2 text-left">Team</th>
                  {COLUMNS.map((c) => <th key={c.key} className="px-1 text-center">{c.label}</th>)}
                  <th className="pl-2 text-right">Space</th>
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
            Goalie: goals saved above expected per game. Prospect depth is not graded yet. Grades compare each team
            with the other 31{sample ? `, using the ${sample}` : ""}. Space is the cap ceiling minus NHL roster
            cap hits and retained salary.
          </p>
        </Panel>

        <div className="space-y-6">
          <Panel title="Top 10 trade targets" note="Ranked by chatter and sentiment">
            <Unavailable>
              Trade targets, with the teams that fit each one best, appear once sentiment scoring and our WAR estimate are in place.
            </Unavailable>
          </Panel>
          <Panel title="Top 10 undervalued" note="Performance percentile minus fan sentiment">
            <Unavailable>The most undervalued players appear once fan sentiment scoring is switched on.</Unavailable>
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
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</p>
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
