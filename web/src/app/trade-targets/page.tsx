import Link from "next/link";
import { connection } from "next/server";
import { Info, Unavailable } from "@/components/ui";
import { definition } from "@/lib/glossary";
import { withDb } from "@/lib/db";
import { money } from "@/lib/format";
import { availability, isBuyLow, needFit, NEED_LABELS, unlikelyAvailable } from "@/lib/needs";
import { getTeams, getTeamBuyingPower, getTradeTargets, type TargetFilters, type TeamNeed, type TradeTarget } from "@/lib/queries";
import { currentSeason } from "@/lib/seasons";

export const metadata = { title: "Trade Targets" };

type Params = Record<string, string | string[] | undefined>;
const one = (p: Params, k: string) => (typeof p[k] === "string" ? (p[k] as string) : undefined);

const AGE = { any: [undefined, undefined], "23-31": [23, 31], u27: [undefined, 26], "30+": [30, undefined] } as const;
const CAP = { any: undefined, "3": 3_000_000, "5": 5_000_000, "7.5": 7_500_000 } as const;
const TERM = { any: [undefined, undefined], "1": [1, 1], "1-2": [1, 2], "1-5": [1, 5], "3+": [3, undefined] } as const;

type Signal = { label: string; cls: string };

// Signal tags (CLAUDE.md section 7).
function signal(t: TradeTarget, season: number): Signal {
  if (isBuyLow(t)) return { label: "Buy-low", cls: "bg-positive-soft text-positive" };
  if (t.surplus != null && t.surplus >= 1_500_000) return { label: "Value", cls: "bg-positive-soft text-positive" };
  if (t.surplus != null && t.surplus <= -2_000_000) return { label: "Risk", cls: "bg-negative-soft text-negative" };
  if (t.end_season === season && (t.age ?? 0) >= 30 && t.expiry_status === "UFA") return { label: "Rental", cls: "bg-border-soft" };
  if (t.end_season === season) return { label: "Contract yr", cls: "bg-border-soft" };
  return { label: "Neutral", cls: "bg-border-soft text-muted" };
}

// Share of salary the seller must retain for the contract to fit (0 = fits, over 50 = cannot fit).
function retentionNeeded(hit: number, space: number | null): number | null {
  if (space == null) return null;
  if (hit <= space) return 0;
  return Math.ceil(((hit - Math.max(space, 0)) / hit) * 100);
}

function capFitLabel(ret: number | null): string {
  if (ret == null) return "—";
  if (ret === 0) return "Fits";
  return ret <= 50 ? `${ret}% ret.` : "No fit";
}

// Sortable columns: key -> value to sort by (higher first unless the column reads better ascending).
type Ctx = { needs: TeamNeed[]; space: number | null; season: number };
const SORTS: Record<string, { label: string; value: (t: TradeTarget, c: Ctx) => number | string | null; asc?: boolean }> = {
  name: { label: "Player", value: (t) => t.name, asc: true },
  team: { label: "Team", value: (t) => t.team, asc: true },
  status: { label: "Team status", value: (t) => (t.power_rank == null ? null : -t.power_rank) },
  pos: { label: "Pos", value: (t) => t.position, asc: true },
  age: { label: "Age", value: (t) => t.age, asc: true },
  cap: { label: "Cap hit", value: (t) => t.cap_hit },
  yrs: { label: "Yrs", value: (t) => t.years, asc: true },
  clause: { label: "Clause", value: (t) => (t.clause && t.clause !== "none" ? t.clause : ""), asc: true },
  fit: { label: "Cap fit", value: (t, c) => retentionNeeded(t.cap_hit, c.space), asc: true },
  fills: { label: "Fills", value: (t, c) => needFit(t, c.needs)?.score ?? null },
  war: { label: "WAR", value: (t) => t.war_proj },
  surplus: { label: "Surplus", value: (t) => t.surplus },
  fans: { label: "Fans", value: (t) => t.fans },
  beat: { label: "Beat", value: (t) => t.beat },
  chatter: { label: "Chatter", value: (t) => t.chatter },
  signal: { label: "Signal", value: (t, c) => signal(t, c.season).label, asc: true },
};

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
  const available = one(p, "avail") === "1";
  const q = one(p, "q")?.slice(0, 40);
  const sortKey = one(p, "sort") && SORTS[one(p, "sort")!] ? one(p, "sort")! : undefined;
  const dir = one(p, "dir") === "asc" ? "asc" : one(p, "dir") === "desc" ? "desc" : undefined;

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
      team ? getTeamBuyingPower(sql, team.id) : Promise.resolve(undefined),
    ]);
    return { teams, team, targets, power };
  });
  const { teams, team, power } = data;
  const ctx: Ctx = { needs: power?.needs ?? [], space: power?.space ?? null, season };

  let rows = data.targets;
  if (rising) rows = rows.filter((t) => t.chatter > t.chatter_prior);
  if (buyLow) rows = rows.filter(isBuyLow);
  if (available) rows = rows.filter((t) => !unlikelyAvailable(t));

  if (sortKey) {
    const s = SORTS[sortKey];
    const asc = dir ? dir === "asc" : !!s.asc;
    rows = [...rows].sort((a, b) => {
      const x = s.value(a, ctx), y = s.value(b, ctx);
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
      return asc ? c : -c;
    });
  } else if (ctx.needs.length) {
    // Default with a team: how well he fills its needs, weighted by how likely his team is to move him.
    const score = (t: TradeTarget) => (needFit(t, ctx.needs)?.score ?? 0) * availability(t);
    rows = [...rows].sort((a, b) => score(b) - score(a) || (b.war_proj ?? -9) - (a.war_proj ?? -9));
  } else {
    // Default without a team: trade chatter, then projected WAR weighted by availability.
    rows = [...rows].sort((a, b) => b.chatter - a.chatter || (b.war_proj ?? -9) * availability(b) - (a.war_proj ?? -9) * availability(a));
  }
  rows = rows.slice(0, 100);

  const spike = [...rows].sort((a, b) => b.chatter - a.chatter)[0];
  const bargain = rows.filter(isBuyLow).sort((a, b) => (b.underlying_pct! - b.results_pct!) - (a.underlying_pct! - a.results_pct!))[0];
  const contractYear = rows.filter((t) => t.end_season === season && (t.age ?? 99) < 30 && !unlikelyAvailable(t))
    .sort((a, b) => (b.war_proj ?? -9) - (a.war_proj ?? -9))[0];

  // Links that keep every current filter and change only the sort.
  const base = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (typeof v === "string" && k !== "sort" && k !== "dir" && k !== "v") base.set(k, v);
  const sortHref = (key: string) => {
    const params = new URLSearchParams(base);
    const s = SORTS[key];
    const nowAsc = sortKey === key ? (dir ? dir === "asc" : !!s.asc) : undefined;
    params.set("sort", key);
    params.set("dir", nowAsc === undefined ? (s.asc ? "asc" : "desc") : nowAsc ? "desc" : "asc");
    return `/trade-targets?${params.toString()}`;
  };
  const columns = ["name", "team", "status", "pos", "age", "cap", "yrs", "clause", "fit", ...(ctx.needs.length ? ["fills"] : []), "war", "surplus", "fans", "beat", "chatter", "signal"];
  const leftAligned = new Set(["name", "team", "status", "pos", "clause", "fit", "fills", "signal"]);
  const orderNote = sortKey
    ? `Sorted by ${SORTS[sortKey].label.toLowerCase()}`
    : ctx.needs.length
      ? "Sorted by how well each player fills this team's needs, weighted by how likely his team is to trade him"
      : "Sorted by trade chatter, then projected WAR weighted by how likely his team is to trade him";

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-heading text-4xl font-bold uppercase leading-tight tracking-tight sm:text-5xl">Trade targets</h1>
          <p className="text-sm text-muted">
            {team ? `Scouting for the ${team.name}` : "Pick a team to see cap fit and needs"} · {rows.length} players match · updated after last night&apos;s games
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
        <Check name="avail" on={available} label="Likely available" />
        <Check name="nmc" on={noNmc} label="Exclude full NMC" />
        <Check name="rising" on={rising} label="Chatter rising" />
        <Check name="buylow" on={buyLow} label="Buy-low only" />
        <Field label="Search">
          <input name="q" defaultValue={q} placeholder="Player or team" className="w-40 rounded-md border border-border bg-surface px-2 py-1.5" />
        </Field>
        <button className="rounded-full bg-ink px-4 py-1.5 font-semibold text-surface">Apply</button>
      </form>

      <section className="overflow-x-auto rounded-lg border border-border bg-surface px-4 pb-3">
        <p className="pt-3 text-xs text-muted">{orderNote}. Click any column heading to sort; click again to reverse.</p>
        {rows.length === 0 ? (
          <div className="py-4"><Unavailable>No players match these filters.</Unavailable></div>
        ) : (
          <table className="w-full min-w-max border-collapse text-sm">
            <thead>
              <tr className="border-b border-border text-xs font-semibold uppercase tracking-wide text-muted">
                {columns.map((key, i) => {
                  const active = sortKey === key;
                  const asc = active ? (dir ? dir === "asc" : !!SORTS[key].asc) : null;
                  return (
                    <th key={key} className={`py-3 ${i === 0 ? "pr-3" : "px-2"} ${leftAligned.has(key) ? "text-left" : "text-right"}`}>
                      <Link href={sortHref(key)} className={`hover:text-ink ${active ? "text-ink" : ""}`}>
                        {SORTS[key].label}{active ? (asc ? " ▲" : " ▼") : ""}
                      </Link>
                      {definition(SORTS[key].label) && (
                        <Info text={definition(SORTS[key].label)!} align={i < columns.length / 2 ? "left" : "right"} />
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => {
                const sig = signal(t, season);
                const ret = retentionNeeded(t.cap_hit, ctx.space);
                const fit = capFitLabel(ret);
                const fill = needFit(t, ctx.needs);
                return (
                  <tr key={t.player_id} className={`border-b border-border-soft ${unlikelyAvailable(t) ? "opacity-60" : ""}`}>
                    <td className="py-2 pr-3 text-left font-semibold"><Link href={`/player/${t.player_id}`} className="hover:underline">{t.name}</Link></td>
                    <td className="px-2"><Link href={`/team/${t.team}`} className="hover:underline">{t.team}</Link></td>
                    <td className="px-2 text-xs">
                      {t.team_status ?? "—"}
                      {unlikelyAvailable(t) && <span className="ml-1 rounded bg-border-soft px-1 font-semibold">Core</span>}
                    </td>
                    <td className="px-2">{t.position}</td>
                    <td className="px-2 text-right font-mono">{t.age ?? "—"}</td>
                    <td className="px-2 text-right font-mono">{money(t.cap_hit)}</td>
                    <td className="px-2 text-right font-mono">{t.years}</td>
                    <td className="px-2 font-mono">{t.clause && t.clause !== "none" ? t.clause : "None"}</td>
                    <td className={`px-2 font-mono font-semibold ${fit === "Fits" ? "text-positive" : fit === "No fit" ? "text-negative" : ""}`}>{fit}</td>
                    {ctx.needs.length > 0 && (
                      <td className={`px-2 text-xs ${fill && fill.pctile >= 70 ? "font-semibold text-positive" : "text-muted"}`}>
                        {fill ? `${NEED_LABELS[fill.category] ?? fill.category} · ${Math.round(fill.pctile)}` : "—"}
                      </td>
                    )}
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
          Team status comes from our power rating (points percentage, goal differential, and 5v5 expected goals share,
          leaning on last season until a team has played enough games): top 10 Contender, bottom 10 Seller once teams have played 20 games (Bubble before that). A
          contender&apos;s six best players by projected WAR are marked Core and shown faded, since contenders rarely move
          them. Cap fit is the share of salary the selling team would need to retain (50% maximum). Fills is his
          percentile at his position in the team&apos;s weakest category he helps. WAR is PuckSleuth&apos;s projection per 84
          games; Surplus compares the cap hit with our market estimate (hover the i next to Surplus for how it is calculated). Players traded, signed, extended, or claimed off waivers in the last 120 days are left out. Buy-low: his underlying play (5v5 expected goals
          share and chance quality) ranks well above his results (goal share and points), with bad luck behind the gap.
        </p>
      </section>

      <div className="grid gap-4 md:grid-cols-3">
        {spike && spike.chatter > 0 && (
          <Alert tone="negative" kind="Most trade chatter" title={`${spike.name}, ${spike.chatter} mentions this week`}
            text={`${spike.team} (${spike.team_status ?? "—"}) · ${money(spike.cap_hit)} for ${spike.years} more season${spike.years === 1 ? "" : "s"}.`} id={spike.player_id} />
        )}
        {bargain && (
          <Alert tone="positive" kind="Buy-low signal" title={bargain.name}
            text={`His team has ${Math.round((bargain.xgf_pct ?? 0) * 100)}% of the expected goals with him on the ice but only ${Math.round((bargain.gf_pct ?? 0) * 100)}% of the actual goals. Results are lagging his play.`} id={bargain.player_id} />
        )}
        {contractYear && (
          <Alert tone="neutral" kind="Contract year" title={`${contractYear.name}, ${contractYear.expiry_status ?? "free agent"} next summer`}
            text={`Projected ${contractYear.war_proj?.toFixed(1) ?? "—"} WAR per season at age ${contractYear.age}, on ${money(contractYear.cap_hit)}.`} id={contractYear.player_id} />
        )}
      </div>
    </main>
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
