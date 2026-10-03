import Link from "next/link";
import { connection } from "next/server";
import { Unavailable } from "@/components/ui";
import { withDb } from "@/lib/db";
import { money } from "@/lib/format";
import { isBuyLow, needFit, NEED_LABELS } from "@/lib/needs";
import { getTeams, getTeamBuyingPower, getTradeTargets, type TargetFilters, type TradeTarget } from "@/lib/queries";
import { currentSeason } from "@/lib/seasons";

export const metadata = { title: "Trade Targets" };


type Params = Record<string, string | string[] | undefined>;
const one = (p: Params, k: string) => (typeof p[k] === "string" ? (p[k] as string) : undefined);

const AGE = { any: [undefined, undefined], "23-31": [23, 31], u27: [undefined, 26], "30+": [30, undefined] } as const;
const CAP = { any: undefined, "3": 3_000_000, "5": 5_000_000, "7.5": 7_500_000 } as const;
const TERM = { any: [undefined, undefined], "1": [1, 1], "1-2": [1, 2], "1-5": [1, 5], "3+": [3, undefined] } as const;

type Signal = { label: string; cls: string };

// Signal tags (CLAUDE.md section 7). Perception gap = performance percentile minus fan score.
function signal(t: TradeTarget, season: number): Signal {
  if (isBuyLow(t)) return { label: "Buy-low", cls: "bg-positive-soft text-positive" };
  if (t.surplus != null && t.surplus >= 1_500_000) return { label: "Value", cls: "bg-positive-soft text-positive" };
  if (t.surplus != null && t.surplus <= -2_000_000) return { label: "Risk", cls: "bg-negative-soft text-negative" };
  if (t.end_season === season && (t.age ?? 0) >= 30 && t.expiry_status === "UFA") return { label: "Rental", cls: "bg-border-soft" };
  if (t.end_season === season) return { label: "Contract yr", cls: "bg-border-soft" };
  return { label: "Neutral", cls: "bg-border-soft text-muted" };
}

function capFit(hit: number, space: number | null): string {
  if (space == null) return "—";
  if (hit <= space) return "Fits";
  const pct = Math.ceil(((hit - Math.max(space, 0)) / hit) * 100);
  return pct <= 50 ? `${pct}% ret.` : "No fit";
}

function Trend({ v }: { v: number | null }) {
  if (v == null || Math.abs(v) < 3) return null;
  return v > 0 ? <span className="ml-1 text-positive">▲</span> : <span className="ml-1 text-negative">▼</span>;
}

export default async function TradeTargetsPage({ searchParams }: PageProps<"/trade-targets">) {
  await connection();
  const p = (await searchParams) as Params;
  const season = currentSeason();
  const teamCode = one(p, "team")?.toUpperCase();
  const pos = (["FD", "F", "D", "G", "all"] as const).find((x) => x === one(p, "pos")) ?? "FD";
  const age = (Object.keys(AGE) as (keyof typeof AGE)[]).find((k) => k === one(p, "age")) ?? "any";
  const cap = (Object.keys(CAP) as (keyof typeof CAP)[]).find((k) => k === one(p, "cap")) ?? "any";
  const term = (Object.keys(TERM) as (keyof typeof TERM)[]).find((k) => k === one(p, "term")) ?? "any";
  const noNmc = one(p, "nmc") === "1";
  const rising = one(p, "rising") === "1";
  const buyLow = one(p, "buylow") === "1";
  const q = one(p, "q")?.slice(0, 40);

  const data = await withDb(async (sql) => {
    const teams = await getTeams(sql);
    const team = teams.find((t) => t.abbrev === teamCode);
    const filters: TargetFilters = {
      exceptTeamId: team?.id, group: pos === "all" ? undefined : pos,
      minAge: AGE[age][0], maxAge: AGE[age][1], maxCap: CAP[cap], minYears: TERM[term][0], maxYears: TERM[term][1],
      noNmc, search: q,
    };
    const [targets, power] = await Promise.all([
      getTradeTargets(sql, season, filters),
      team ? getTeamBuyingPower(sql, team.id, season) : Promise.resolve(undefined),
    ]);
    return { teams, team, targets, power };
  });
  const { teams, team, power } = data;
  let rows = data.targets;
  if (rising) rows = rows.filter((t) => t.chatter > t.chatter_prior);
  if (buyLow) rows = rows.filter(isBuyLow);
  const needs = power?.needs ?? [];
  if (needs.length) {
    // With a team chosen: best fit for its needs first, then projected WAR.
    rows = [...rows].sort((a, b) => (needFit(b, needs)?.score ?? -1) - (needFit(a, needs)?.score ?? -1)
      || (b.war_proj ?? -9) - (a.war_proj ?? -9));
  }
  rows = rows.slice(0, 100);

  const spike = [...rows].sort((a, b) => b.chatter - a.chatter)[0];
  const bargain = rows.filter(isBuyLow).sort((a, b) => (b.perf_vs_fans! - b.fans_pctile!) - (a.perf_vs_fans! - a.fans_pctile!))[0];
  const contractYear = rows.filter((t) => t.end_season === season && (t.age ?? 99) < 30)
    .sort((a, b) => (b.war_proj ?? -9) - (a.war_proj ?? -9))[0];

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-heading text-4xl font-bold uppercase leading-tight tracking-tight sm:text-5xl">Trade targets</h1>
          <p className="text-sm text-muted">
            {team ? `Scouting for the ${team.name}` : "Pick a team to see cap fit"} · {rows.length} players match · updated after last night&apos;s games
          </p>
        </div>
        {team && power && (
          <div className="flex gap-3">
            <div className="rounded-lg border border-border bg-surface p-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted">Your cap space</p>
              <p className={`font-mono text-xl ${power.space != null && power.space < 0 ? "text-negative" : ""}`}>{money(power.space)}</p>
            </div>
            <div className="max-w-xs rounded-lg border border-border bg-surface p-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted">Roster need</p>
              <p className="font-semibold">{power.needs.length ? power.needs.slice(0, 3).map((n) => NEED_LABELS[n.category] ?? n.category).join(", ") : "No glaring needs"}</p>
            </div>
          </div>
        )}
      </div>

      <form action="/trade-targets" className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface p-4 text-sm">
        <Field label="Scouting for">
          <select name="team" defaultValue={team?.abbrev ?? ""} className="rounded-md border border-border bg-surface px-2 py-1.5">
            <option value="">Any team</option>
            {teams.map((t) => <option key={t.abbrev} value={t.abbrev}>{t.name}</option>)}
          </select>
        </Field>
        <Field label="Position">
          <select name="pos" defaultValue={pos} className="rounded-md border border-border bg-surface px-2 py-1.5">
            <option value="FD">Forwards + D</option><option value="F">Forwards</option><option value="D">Defense</option>
            <option value="G">Goalies</option><option value="all">All</option>
          </select>
        </Field>
        <Field label="Age">
          <select name="age" defaultValue={age} className="rounded-md border border-border bg-surface px-2 py-1.5">
            <option value="any">Any</option><option value="23-31">23-31</option><option value="u27">Under 27</option><option value="30+">30+</option>
          </select>
        </Field>
        <Field label="Cap hit">
          <select name="cap" defaultValue={cap} className="rounded-md border border-border bg-surface px-2 py-1.5">
            <option value="any">Any</option><option value="3">Under $3M</option><option value="5">Under $5M</option><option value="7.5">Under $7.5M</option>
          </select>
        </Field>
        <Field label="Term left">
          <select name="term" defaultValue={term} className="rounded-md border border-border bg-surface px-2 py-1.5">
            <option value="any">Any</option><option value="1">1 yr</option><option value="1-2">1-2 yrs</option><option value="1-5">1-5 yrs</option><option value="3+">3+ yrs</option>
          </select>
        </Field>
        <Check name="nmc" on={noNmc} label="Exclude full NMC" />
        <Check name="rising" on={rising} label="Chatter rising" />
        <Check name="buylow" on={buyLow} label="Buy-low only" />
        <Field label="Search">
          <input name="q" defaultValue={q} placeholder="Player or team" className="w-40 rounded-md border border-border bg-surface px-2 py-1.5" />
        </Field>
        <button className="rounded-full bg-ink px-4 py-1.5 font-semibold text-surface">Apply</button>
      </form>

      <section className="overflow-x-auto rounded-lg border border-border bg-surface px-4 pb-3">
        {rows.length === 0 ? (
          <div className="py-4"><Unavailable>No players match these filters.</Unavailable></div>
        ) : (
          <table className="w-full min-w-max border-collapse text-sm">
            <thead>
              <tr className="border-b border-border text-xs font-semibold uppercase tracking-wide text-muted">
                {["Player", "Team", "Pos", "Age", "Cap hit", "Yrs", "Clause", "Cap fit", ...(needs.length ? ["Fills"] : []), "WAR", "Surplus", "Fans", "Beat", "Chatter", "Signal"].map((h, i) => (
                  <th key={h} className={`py-3 ${i === 0 ? "pr-3 text-left" : ["Team", "Pos", "Clause", "Cap fit", "Fills", "Signal"].includes(h) ? "px-2 text-left" : "px-2 text-right"}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => {
                const sig = signal(t, season);
                const fit = capFit(t.cap_hit, power?.space ?? null);
                return (
                  <tr key={t.player_id} className="border-b border-border-soft">
                    <td className="py-2 pr-3 text-left font-semibold"><Link href={`/player/${t.player_id}`} className="hover:underline">{t.name}</Link></td>
                    <td className="px-2"><Link href={`/team/${t.team}`} className="hover:underline">{t.team}</Link></td>
                    <td className="px-2">{t.position}</td>
                    <td className="px-2 text-right font-mono">{t.age ?? "—"}</td>
                    <td className="px-2 text-right font-mono">{money(t.cap_hit)}</td>
                    <td className="px-2 text-right font-mono">{t.years}</td>
                    <td className="px-2 font-mono">{t.clause && t.clause !== "none" ? t.clause : "None"}</td>
                    <td className={`px-2 font-mono font-semibold ${fit === "Fits" ? "text-positive" : fit === "No fit" ? "text-negative" : ""}`}>{fit}</td>
                    {needs.length > 0 && <FillsCell fill={needFit(t, needs)} />}
                    <td className="px-2 text-right font-mono">{t.war_proj == null ? "—" : t.war_proj.toFixed(1)}</td>
                    <td className={`px-2 text-right font-mono ${t.surplus == null ? "" : t.surplus >= 0 ? "text-positive" : "text-negative"}`}>
                      {t.surplus == null ? "—" : `${t.surplus >= 0 ? "+" : "−"}${money(Math.abs(t.surplus))}`}
                    </td>
                    <td className="px-2 text-right font-mono">{t.fans == null ? "—" : Math.round(t.fans)}<Trend v={t.fans_trend} /></td>
                    <td className="px-2 text-right font-mono">{t.beat == null ? "—" : Math.round(t.beat)}<Trend v={t.beat_trend} /></td>
                    <td className="px-2 text-right font-mono">{t.chatter}</td>
                    <td className="px-2"><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${sig.cls}`}>{sig.label}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <p className="mt-3 text-xs text-muted">
          Cap fit shows the share of salary the selling team would need to retain for the contract to fit (50% maximum).
          Fills is his percentile at his position in the team&apos;s weakest graded category he helps (a Need counts more than
          a Thin), and the list is sorted by it. WAR is PuckSleuth&apos;s projection per 82 games. Surplus compares the cap hit with our market estimate. Fans and
          Beat are sentiment scores 0-100 with the 14-day trend; Chatter is trade mentions in the last 7 days. Buy-low means
          his performance ranks in the top 30% at his position and at least 40 percentile points above where fans rank him.
        </p>
      </section>

      <div className="grid gap-4 md:grid-cols-3">
        {spike && spike.chatter > 0 && (
          <Alert tone="negative" kind="Most trade chatter" title={`${spike.name}, ${spike.chatter} mentions this week`}
            text={`${spike.team} · ${money(spike.cap_hit)} through ${spike.years} more season${spike.years === 1 ? "" : "s"}.`} id={spike.player_id} />
        )}
        {bargain && (
          <Alert tone="positive" kind="Buy-low signal" title={bargain.name}
            text={`Among players fans talk about at his position, his performance ranks in the ${Math.round(bargain.perf_vs_fans!)}th percentile but his fan score in the ${Math.round(bargain.fans_pctile!)}th. Perception is lagging performance.`} id={bargain.player_id} />
        )}
        {contractYear && (
          <Alert tone="neutral" kind="Contract year" title={`${contractYear.name}, ${contractYear.expiry_status ?? "free agent"} next summer`}
            text={`Projected ${contractYear.war_proj?.toFixed(1) ?? "—"} WAR per 82 at age ${contractYear.age}, on ${money(contractYear.cap_hit)}.`} id={contractYear.player_id} />
        )}
      </div>
    </main>
  );
}

function FillsCell({ fill }: { fill: { category: string; pctile: number } | null }) {
  if (!fill) return <td className="px-2 text-muted">—</td>;
  const strong = fill.pctile >= 70;
  return (
    <td className={`px-2 text-xs ${strong ? "font-semibold text-positive" : "text-muted"}`}>
      {NEED_LABELS[fill.category] ?? fill.category} · {Math.round(fill.pctile)}
    </td>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</span>
      {children}
    </label>
  );
}

function Check({ name, on, label }: { name: string; on: boolean; label: string }) {
  return (
    <label className="flex items-center gap-2 rounded-full border border-border px-3 py-1.5">
      <input type="checkbox" name={name} value="1" defaultChecked={on} />
      {label}
    </label>
  );
}

function Alert({ kind, title, text, tone, id }: { kind: string; title: string; text: string; tone: "positive" | "negative" | "neutral"; id: number }) {
  const color = tone === "positive" ? "text-positive" : tone === "negative" ? "text-negative" : "text-muted";
  return (
    <Link href={`/player/${id}`} className="rounded-lg border border-border bg-surface p-4 hover:border-ink">
      <p className={`text-xs font-semibold uppercase tracking-wide ${color}`}>{kind}</p>
      <p className="mt-1 font-semibold">{title}</p>
      <p className="mt-1 text-sm text-muted">{text}</p>
    </Link>
  );
}
