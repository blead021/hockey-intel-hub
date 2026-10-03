import Link from "next/link";
import { Fragment } from "react";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { TeamSelect } from "@/components/team-select";
import { Label, SeasonPicker, StatCard, Unavailable } from "@/components/ui";
import { withDb } from "@/lib/db";
import { faceoffPct, money, num, season as seasonLabel, shortDate, signed, svPct, toi } from "@/lib/format";
import {
  getCapCeiling,
  getCapCharges,
  getCapUpdatedAt,
  getTeamCapSpace,
  getUndervalued,
  getContractCount,
  getEnabledSources,
  getExpiring,
  getTeamFutureCap,
  type FutureCapRow,
  getLoadedSeasons,
  getPlayerSentiment,
  getReserveList,
  getRetainedCharges,
  getRosterGoalies,
  getRosterSkaters,
  getTeam,
  getTeamChatter,
  getTeams,
  getTeamSummary,
  type PlayerSentiment,
  type ReservePlayer,
  type CapCharge,
  type Undervalued,
  type RetainedCharge,
  type RosterGoalie,
  type RosterSkater,
} from "@/lib/queries";
import { currentSeason, parseSeason } from "@/lib/seasons";

export async function generateMetadata({ params }: PageProps<"/team/[abbrev]">) {
  const { abbrev } = await params;
  return { title: `${abbrev.toUpperCase()} roster` };
}

const MAX_RETAINED = 3;

function ordinal(n: number | null): string {
  if (n == null) return "—";
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
}

function yearsLeft(endSeason: number | null, season: number): string {
  if (!endSeason) return "—";
  return String(Math.floor(endSeason / 10000) - Math.floor(season / 10000) + 1);
}

function TrendArrow({ value }: { value: number | null | undefined }) {
  if (value == null || Math.abs(value) < 1) return null;
  return value > 0 ? <span className="ml-1 text-positive">▲</span> : <span className="ml-1 text-negative">▼</span>;
}

export default async function TeamPage({ params, searchParams }: PageProps<"/team/[abbrev]">) {
  await connection();
  const { abbrev } = await params;
  const requested = parseSeason((await searchParams).season);
  const current = currentSeason();

  const data = await withDb(async (sql) => {
    const team = await getTeam(sql, abbrev);
    if (!team) return null;
    const season = requested ?? current;
    const isCurrent = season === current;
    const [teams, seasons, summary, skaters, goalies, sources, ceiling, expiring, chatter, retained, reserve, contractCount, charges, capAsOf, undervalued, capSpace, future] = await Promise.all([
      getTeams(sql),
      getLoadedSeasons(sql),
      getTeamSummary(sql, team.id, season),
      getRosterSkaters(sql, team.id, season, isCurrent),
      getRosterGoalies(sql, team.id, season, isCurrent),
      getEnabledSources(sql),
      getCapCeiling(sql, season),
      getExpiring(sql, team.id, season),
      getTeamChatter(sql, team.id),
      getRetainedCharges(sql, team.id, season),
      isCurrent ? getReserveList(sql, team.id, season) : Promise.resolve([]),
      getContractCount(sql, team.id, season),
      isCurrent ? getCapCharges(sql, team.id) : Promise.resolve([] as CapCharge[]),
      getCapUpdatedAt(sql),
      isCurrent ? getUndervalued(sql, season, team.id, 4) : Promise.resolve([] as Undervalued[]),
      isCurrent ? getTeamCapSpace(sql, team.id) : Promise.resolve(undefined),
      isCurrent ? getTeamFutureCap(sql, team.id, season) : Promise.resolve(undefined),
    ]);
    const sentiment = await getPlayerSentiment(sql, [...skaters, ...goalies].map((p) => p.id));
    return { team, teams, seasons, season, isCurrent, summary, skaters, goalies, sources, ceiling, expiring, chatter, retained, reserve, contractCount, charges, capAsOf, undervalued, capSpace, future, sentiment };
  });
  if (!data) notFound();
  const { team, teams, seasons, season, isCurrent, summary, skaters, goalies, sources, ceiling, expiring, chatter, retained, reserve, contractCount, charges, capAsOf, undervalued, capSpace, future, sentiment } = data;

  const showContracts = sources.has("contracts_csv");
  const forwards = skaters.filter((s) => s.position !== "D");
  const defense = skaters.filter((s) => s.position === "D");
  const capOf = (list: { cap_hit: number | null }[]) => list.reduce((sum, p) => sum + (Number(p.cap_hit) || 0), 0);
  const retainedCap = retained.reduce((sum, r) => sum + r.charge, 0);
  // This season: every contract the team holds (team_cap_charges), so injured and buried players count.
  // Past seasons: the players who played for the team, plus retained salary.
  const offRoster = charges.filter((c) => c.kind !== "roster" && c.kind !== "retained");
  const capCommitted = isCurrent
    ? charges.reduce((sum, c) => sum + c.charge, 0)
    : capOf(skaters) + capOf(goalies) + retainedCap;
  const hasContracts = [...skaters, ...goalies].some((p) => p.cap_hit != null);
  const pickerSeasons = [...new Set([current, ...seasons])].sort((a, b) => b - a);
  const record = summary?.gp ? `${summary.w}-${summary.l}-${summary.otl} · ${summary.points} PTS` : seasonLabel(season);
  const pct1 = (v: number | null | undefined) => (v == null ? "—" : (v * 100).toFixed(1));
  const cols = showContracts ? 17 : 13;

  return (
    <main className="mx-auto max-w-7xl px-4 py-8">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-widest text-muted">
            {team.division ? `${team.division} Division · ` : ""}
            {record}
          </p>
          <h1 className="font-heading text-4xl font-bold uppercase leading-tight tracking-tight sm:text-5xl">{team.name} roster</h1>
          <SeasonPicker seasons={pickerSeasons} current={season} hrefFor={(s) => `/team/${team.abbrev}?season=${s}`} />
        </div>
        <TeamSelect teams={teams.map((t) => ({ abbrev: t.abbrev, name: t.name }))} current={team.abbrev} season={season} />
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Cap committed" value={hasContracts ? money(capCommitted) : "—"} detail={ceiling ? `of ${money(ceiling)} ceiling${isCurrent && capAsOf ? ` · as of ${shortDate(capAsOf)}` : ""}` : "ceiling not set"} />
        <StatCard
          label="Cap space"
          value={hasContracts && ceiling ? money(capSpace ? capSpace.space : ceiling - capCommitted) : "—"}
          detail={capSpace && capSpace.ltir_relief > 0
            ? `Using ${money(capSpace.ltir_relief)} of LTIR relief · retained slots ${retained.length} of ${MAX_RETAINED}`
            : `Retained slots used: ${retained.length} of ${MAX_RETAINED}`}
        />
        <StatCard label="Active roster" value={skaters.length + goalies.length} detail={showContracts && isCurrent ? `${contractCount} of 50 NHL contracts` : isCurrent ? "on the current roster" : "played this season"} />
        <StatCard label="5v5 xGF%" value={pct1(summary?.xgf_pct)} detail={summary?.xgf_rank ? `${ordinal(summary.xgf_rank)} in NHL` : undefined} />
        <StatCard
          label="PP% / PK%"
          value={`${pct1(summary?.pp_pct)} / ${pct1(summary?.pk_pct)}`}
          detail={summary?.pp_rank ? `PP ${ordinal(summary.pp_rank)} · PK ${ordinal(summary.pk_rank)}` : undefined}
        />
        <StatCard
          label="Fan sentiment"
          value={summary?.fan_score == null ? "—" : Math.round(summary.fan_score)}
          detail={
            summary?.fan_score == null ? "scores begin once sentiment scoring is on" : summary.fan_trend == null ? undefined : (
              <span className={summary.fan_trend >= 0 ? "text-positive" : "text-negative"}>
                {summary.fan_trend >= 0 ? "▲" : "▼"} {Math.abs(Math.round(summary.fan_trend))} in 14 days
              </span>
            )
          }
        />
      </div>

      {undervalued.length > 0 && <UndervaluedHere rows={undervalued} />}

      <div className="mt-6 overflow-x-auto rounded-lg border border-border bg-surface px-4 pb-4">
        <table className="w-full min-w-max border-collapse text-sm">
          <thead>
            <tr className="border-b border-border text-xs font-semibold uppercase tracking-wide text-muted">
              <th className="sticky left-0 z-10 bg-surface py-3 pr-3 text-left">Player</th>
              {["Pos", "Age", "GP", "G", "A", "P", "TOI", "FO%", "xGF%", "WAR"].map((h) => (
                <th key={h} className="px-2 py-3 text-right"><Label text={h} align={["Cap hit", "Yrs", "Expiry", "Clause", "Type"].includes(h) ? "right" : "left"} /></th>
              ))}
              {showContracts && ["Cap hit", "Yrs", "Expiry", "Clause"].map((h) => (
                <th key={h} className={`px-2 py-3 ${h === "Expiry" || h === "Clause" ? "text-left" : "text-right"}`}><Label text={h} align={["Cap hit", "Yrs", "Expiry", "Clause", "Type"].includes(h) ? "right" : "left"} /></th>
              ))}
              <th className="px-2 py-3 text-right"><Label text="Fans" align="right" /></th>
              <th className="py-3 pl-2 text-right"><Label text="Chatter" align="right" /></th>
            </tr>
          </thead>
          <tbody>
            <GroupHeader title="Forwards" count={forwards.length} total={showContracts ? capOf(forwards) : null} cols={cols} />
            {forwards.map((p) => <SkaterRow key={p.id} p={p} s={sentiment.get(p.id)} season={season} showContracts={showContracts} />)}
            <GroupHeader title="Defense" count={defense.length} total={showContracts ? capOf(defense) : null} cols={cols} />
            {defense.map((p) => <SkaterRow key={p.id} p={p} s={sentiment.get(p.id)} season={season} showContracts={showContracts} />)}
          </tbody>
        </table>

        <h2 className="mt-6 font-heading text-2xl font-semibold uppercase tracking-tight">
          Goalies <span className="font-sans text-sm font-normal normal-case tracking-normal text-muted">{goalies.length} {isCurrent ? "on roster" : "played"}</span>
        </h2>
        {goalies.length === 0 ? (
          <Unavailable>No goalies yet for this season.</Unavailable>
        ) : (
          <table className="mt-2 w-full min-w-max border-collapse text-sm">
            <thead>
              <tr className="border-b border-border text-xs font-semibold uppercase tracking-wide text-muted">
                <th className="sticky left-0 z-10 bg-surface py-3 pr-3 text-left">Player</th>
                {["Age", "GP", "SV%", "GAA", "GSAx", "WAR"].map((h) => <th key={h} className="px-2 py-3 text-right"><Label text={h} align={["Cap hit", "Yrs", "Expiry", "Clause", "Type"].includes(h) ? "right" : "left"} /></th>)}
                {showContracts && ["Cap hit", "Yrs", "Expiry", "Clause"].map((h) => (
                  <th key={h} className={`px-2 py-3 ${h === "Expiry" || h === "Clause" ? "text-left" : "text-right"}`}><Label text={h} align={["Cap hit", "Yrs", "Expiry", "Clause", "Type"].includes(h) ? "right" : "left"} /></th>
                ))}
                <th className="px-2 py-3 text-right"><Label text="Fans" align="right" /></th>
                <th className="py-3 pl-2 text-right"><Label text="Chatter" align="right" /></th>
              </tr>
            </thead>
            <tbody>
              {goalies.map((g) => <GoalieRow key={g.id} g={g} s={sentiment.get(g.id)} season={season} showContracts={showContracts} />)}
            </tbody>
          </table>
        )}
        <p className="mt-3 text-xs text-muted">
          FO% shown for centers. 5v5 xGF% from our expected goals model. WAR is PuckSleuth&apos;s estimate: wins above a replacement-level player, from our Game Score.
          Fans = fan sentiment 0-100 with 14-day trend. Chatter = trade mentions in the last 7 days.
        </p>
      </div>

      {showContracts && isCurrent && <ReserveList rows={reserve} season={season} />}

      {showContracts && future && <FutureCapGrid future={future} thisSeasonTotal={capCommitted} />}

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        {showContracts && <CapByPosition forwards={capOf(forwards)} defense={capOf(defense)} goalies={capOf(goalies)} retained={retained} offRoster={offRoster} />}
        {showContracts && <Expiring rows={expiring} />}
        <MostChatter rows={chatter} />
      </div>
    </main>
  );
}

function GroupHeader({ title, count, total, cols }: { title: string; count: number; total: number | null; cols: number }) {
  return (
    <tr>
      <td colSpan={cols} className="border-b border-border pb-2 pt-5">
        <span className="font-heading text-xl font-semibold uppercase">{title}</span>
        <span className="ml-2 text-xs text-muted">
          {count} players{total ? ` · ${money(total)}` : ""}
        </span>
      </td>
    </tr>
  );
}

function FansCell({ s }: { s: PlayerSentiment | undefined }) {
  const score = s?.fan_score;
  return (
    <td className="px-2 py-2 text-right font-mono">
      {score == null ? "—" : (
        <span className={score >= 65 ? "text-positive" : score < 50 ? "text-negative" : ""}>
          {Math.round(score)}
          <TrendArrow value={s?.fan_trend} />
        </span>
      )}
    </td>
  );
}

function ChatterCell({ s }: { s: PlayerSentiment | undefined }) {
  return (
    <td className="py-2 pl-2 text-right font-mono">
      {s?.chatter_7d ? <span className={s.spike ? "text-negative" : ""}>{s.chatter_7d}{s.spike && " ▲"}</span> : "0"}
    </td>
  );
}

function ContractCells({ p, season }: { p: { cap_hit: number | null; end_season: number | null; expiry_status: string | null; clause: string | null }; season: number }) {
  return (
    <>
      <td className="px-2 py-2 text-right font-mono">{money(p.cap_hit)}</td>
      <td className="px-2 py-2 text-right font-mono">{yearsLeft(p.end_season, season)}</td>
      <td className="px-2 py-2 text-left font-mono">{p.expiry_status ?? "—"}</td>
      <td className="px-2 py-2 text-left font-mono">{p.clause ? (p.clause === "none" ? "None" : p.clause) : "—"}</td>
    </>
  );
}

function SkaterRow({ p, s, season, showContracts }: { p: RosterSkater; s: PlayerSentiment | undefined; season: number; showContracts: boolean }) {
  return (
    <tr className="border-b border-border-soft">
      <td className="sticky left-0 z-10 bg-surface py-2 pr-3 text-left">
        <Link href={`/player/${p.id}`} className="font-semibold hover:underline">{p.name}</Link>
      </td>
      <td className="px-2 py-2 text-right">{p.position}</td>
      <td className="px-2 py-2 text-right font-mono">{num(p.age)}</td>
      <td className="px-2 py-2 text-right font-mono">{p.gp}</td>
      <td className="px-2 py-2 text-right font-mono">{p.g}</td>
      <td className="px-2 py-2 text-right font-mono">{p.a}</td>
      <td className="px-2 py-2 text-right font-mono">{p.pts}</td>
      <td className="px-2 py-2 text-right font-mono">{p.gp ? toi(p.toi_sec / p.gp) : "—"}</td>
      <td className="px-2 py-2 text-right font-mono">{p.position === "C" ? faceoffPct(p.fow, p.fol).replace("%", "") : "—"}</td>
      <td className={`px-2 py-2 text-right font-mono ${p.xgf_pct == null ? "" : p.xgf_pct >= 0.5 ? "text-positive" : "text-negative"}`}>
        {p.xgf_pct == null ? "—" : (p.xgf_pct * 100).toFixed(1)}
      </td>
      <td className={`px-2 py-2 text-right font-mono ${p.war == null ? "" : p.war >= 0 ? "" : "text-negative"}`}>{p.war == null ? "—" : p.war.toFixed(1)}</td>
      {showContracts && <ContractCells p={p} season={season} />}
      <FansCell s={s} />
      <ChatterCell s={s} />
    </tr>
  );
}

function GoalieRow({ g, s, season, showContracts }: { g: RosterGoalie; s: PlayerSentiment | undefined; season: number; showContracts: boolean }) {
  return (
    <tr className="border-b border-border-soft">
      <td className="sticky left-0 z-10 bg-surface py-2 pr-3 text-left">
        <Link href={`/player/${g.id}`} className="font-semibold hover:underline">{g.name}</Link>
      </td>
      <td className="px-2 py-2 text-right font-mono">{num(g.age)}</td>
      <td className="px-2 py-2 text-right font-mono">{g.gp}</td>
      <td className="px-2 py-2 text-right font-mono">{svPct(g.saves, g.shots_against)}</td>
      <td className="px-2 py-2 text-right font-mono">{g.toi_sec ? num((g.ga * 3600) / g.toi_sec, 2) : "—"}</td>
      <td className={`px-2 py-2 text-right font-mono ${g.gsax == null ? "" : g.gsax >= 0 ? "text-positive" : "text-negative"}`}>
        {g.gsax == null ? "—" : signed(Math.round(g.gsax * 10) / 10)}
      </td>
      <td className={`px-2 py-2 text-right font-mono ${g.war == null ? "" : g.war >= 0 ? "" : "text-negative"}`}>{g.war == null ? "—" : g.war.toFixed(1)}</td>
      {showContracts && <ContractCells p={g} season={season} />}
      <FansCell s={s} />
      <ChatterCell s={s} />
    </tr>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-surface p-5">
      <h2 className="mb-4 font-heading text-2xl font-semibold uppercase tracking-tight">{title}</h2>
      {children}
    </section>
  );
}

const OFF_ROSTER: Record<string, string> = {
  injured: "Injured reserve",
  ltir: "Long-term injured reserve",
  waivers: "On waivers",
  buried: "Buried in the minors",
  unknown: "Off the roster, status unconfirmed",
  "adjustment:buyout": "Buyouts",
  "adjustment:bonus_overage": "Bonus overage from last season",
  "adjustment:dead_cap": "Other dead cap",
};

function CapByPosition({ forwards, defense, goalies, retained, offRoster }: { forwards: number; defense: number; goalies: number; retained: RetainedCharge[]; offRoster: CapCharge[] }) {
  const retainedTotal = retained.reduce((sum, r) => sum + r.charge, 0);
  const groups = Object.keys(OFF_ROSTER)
    .map((kind) => ({ kind, rows: offRoster.filter((c) => c.kind === kind) }))
    .filter((g) => g.rows.length > 0);
  const offTotal = offRoster.reduce((sum, c) => sum + c.charge, 0);
  const total = forwards + defense + goalies + retainedTotal + offTotal;
  if (!total) return <Panel title="Cap by position"><Unavailable>No contracts loaded for this roster.</Unavailable></Panel>;
  const parts = [
    { label: "Forwards", value: forwards, color: "bg-positive" },
    { label: "Defense", value: defense, color: "bg-positive/60" },
    { label: "Goalies", value: goalies, color: "bg-positive/30" },
    ...(retainedTotal ? [{ label: "Retained on traded players", value: retainedTotal, color: "bg-negative/60" }] : []),
    ...groups.map((g) => ({ label: OFF_ROSTER[g.kind], value: g.rows.reduce((sum, c) => sum + c.charge, 0), color: "bg-negative/30" })),
  ];
  return (
    <Panel title="Cap by position">
      <div className="flex h-3 overflow-hidden rounded-full" aria-hidden>
        {parts.map((p) => <div key={p.label} className={p.color} style={{ width: `${(p.value / total) * 100}%` }} />)}
      </div>
      <ul className="mt-4 space-y-2 text-sm">
        {parts.map((p) => (
          <li key={p.label} className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-2"><span className={`inline-block h-3 w-3 rounded-sm ${p.color}`} />{p.label}</span>
            <span className="font-mono">{money(p.value)} · {((p.value / total) * 100).toFixed(1)}%</span>
          </li>
        ))}
      </ul>
      {retained.length > 0 && (
        <p className="mt-3 text-xs text-muted">
          Retained: {retained.map((r) => `${r.name} (${r.team}, ${r.pct}%, ${money(r.charge)})`).join("; ")}.
        </p>
      )}
      {groups.map((g) => (
        <p key={g.kind} className="mt-2 text-xs text-muted">
          {OFF_ROSTER[g.kind]}: {g.rows.map((c) => `${c.name} (${money(c.charge)})`).join("; ")}.
        </p>
      ))}
      <p className="mt-2 text-xs text-muted">
        Players in the minors count only above the buried allowance (league minimum salary plus $375,000). Roster
        status, buyouts, and bonus overages come from team announcements and news, checked daily. LTIR relief is not
        shown.
      </p>
    </Panel>
  );
}

function Expiring({ rows }: { rows: Awaited<ReturnType<typeof getExpiring>> }) {
  const ufa = rows.filter((r) => r.expiry_status === "UFA").length;
  const rfa = rows.filter((r) => r.expiry_status === "RFA").length;
  const off = rows.reduce((sum, r) => sum + (r.cap_hit ?? 0), 0);
  return (
    <Panel title="Expiring this season">
      <div className="mb-3 grid grid-cols-3 gap-2 text-sm">
        <div><p className="text-xs text-muted">Pending UFAs</p><p className="font-mono text-xl">{ufa}</p></div>
        <div><p className="text-xs text-muted">Pending RFAs</p><p className="font-mono text-xl">{rfa}</p></div>
        <div><p className="text-xs text-muted">Cap coming off</p><p className="font-mono text-xl">{money(off)}</p></div>
      </div>
      {rows.length === 0 ? <p className="text-sm text-muted">No contracts end this season.</p> : (
        <ul className="divide-y divide-border-soft text-sm">
          {rows.slice(0, 6).map((r) => (
            <li key={`${r.name}-${r.cap_hit}`} className="flex justify-between gap-2 py-2">
              {r.player_id ? <Link href={`/player/${r.player_id}`} className="font-semibold hover:underline">{r.name}</Link> : <span className="font-semibold">{r.name}</span>}
              <span className="font-mono text-xs text-muted">{r.expiry_status ?? "—"} · {money(r.cap_hit)}{r.age != null ? ` · age ${r.age}` : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function MostChatter({ rows }: { rows: Awaited<ReturnType<typeof getTeamChatter>> }) {
  const top = Math.max(...rows.map((r) => r.chatter_7d), 1);
  return (
    <Panel title="Most trade chatter">
      {rows.length === 0 ? (
        <p className="text-sm text-muted">No trade chatter yet. It appears once sentiment scoring is switched on.</p>
      ) : (
        <ul className="space-y-4">
          {rows.map((r) => (
            <li key={r.player_id}>
              <div className="flex justify-between text-sm">
                <Link href={`/player/${r.player_id}`} className="font-semibold hover:underline">{r.name}</Link>
                <span className="font-mono text-negative">{r.chatter_7d} mentions</span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-border-soft">
                <div className="h-full bg-negative" style={{ width: `${(r.chatter_7d / top) * 100}%` }} />
              </div>
              {r.summary && <p className="mt-1 text-xs text-muted">{r.summary}</p>}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

const CONTRACT_TYPES: Record<string, string> = { entry_level: "ELC", standard: "Standard", extension: "Extension" };

function ReserveList({ rows, season }: { rows: ReservePlayer[]; season: number }) {
  return (
    <section className="mt-6 overflow-x-auto rounded-lg border border-border bg-surface px-4 pb-4">
      <h2 className="mt-4 font-heading text-2xl font-semibold uppercase tracking-tight">
        Reserve list{" "}
        <span className="font-sans text-sm font-normal normal-case tracking-normal text-muted">
          under NHL contract, not on the NHL roster · {rows.length} players
        </span>
      </h2>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-muted">No contracted players outside the NHL roster on file.</p>
      ) : (
        <table className="mt-2 w-full min-w-max border-collapse text-sm">
          <thead>
            <tr className="border-b border-border text-xs font-semibold uppercase tracking-wide text-muted">
              <th className="py-3 pr-3 text-left">Player</th>
              {["Pos", "Age", "Cap hit", "Yrs", "Expiry", "Type"].map((h) => (
                <th key={h} className={`px-2 py-3 ${h === "Expiry" || h === "Type" ? "text-left" : "text-right"}`}><Label text={h} align={["Cap hit", "Yrs", "Expiry", "Clause", "Type"].includes(h) ? "right" : "left"} /></th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.name}-${r.end_season}`} className="border-b border-border-soft">
                <td className="py-2 pr-3 text-left">
                  {r.player_id ? <Link href={`/player/${r.player_id}`} className="font-semibold hover:underline">{r.name}</Link> : <span className="font-semibold">{r.name}</span>}
                </td>
                <td className="px-2 py-2 text-right">{r.position ?? "—"}</td>
                <td className="px-2 py-2 text-right font-mono">{num(r.age)}</td>
                <td className="px-2 py-2 text-right font-mono">{r.cap_hit == null ? "unknown" : money(r.cap_hit)}</td>
                <td className="px-2 py-2 text-right font-mono">{yearsLeft(r.end_season, season)}</td>
                <td className="px-2 py-2 text-left font-mono">{r.expiry_status ?? "—"}</td>
                <td className="px-2 py-2 text-left">{r.contract_type ? CONTRACT_TYPES[r.contract_type] ?? r.contract_type : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="mt-3 text-xs text-muted">
        Prospects and depth players signed to NHL contracts, including two-way deals. Players on AHL-only contracts are not listed.
      </p>
    </section>
  );
}

// "Undervalued on this roster" (CLAUDE.md section 6): the team's top 4 by perception gap, with Claude's reason.
function UndervaluedHere({ rows }: { rows: Undervalued[] }) {
  return (
    <section className="mt-6 rounded-lg border border-border bg-surface p-5">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-heading text-2xl font-semibold uppercase tracking-tight">Undervalued on this roster</h2>
        <p className="text-xs text-muted">Performance well above what fans think · biggest gaps first</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {rows.map((u) => (
          <Link key={u.player_id} href={`/player/${u.player_id}`} className="rounded-lg border border-border p-3 hover:border-ink">
            <p className="font-semibold">{u.name}</p>
            <p className="text-xs text-muted">{u.position} · age {u.age ?? "—"} · {money(u.cap_hit)}</p>
            <div className="mt-2 grid grid-cols-3 gap-1 text-center text-xs">
              <div><p className="text-muted">Fans</p><p className="font-mono text-base text-negative">{Math.round(u.fans)}</p></div>
              <div><p className="text-muted">Perf.</p><p className="font-mono text-base text-positive">{Math.round(u.perf_pct)}</p></div>
              <div><p className="text-muted">Surplus</p><p className={`font-mono text-base ${u.surplus == null ? "" : u.surplus >= 0 ? "text-positive" : "text-negative"}`}>{u.surplus == null ? "—" : `${u.surplus >= 0 ? "+" : "−"}${money(Math.abs(u.surplus))}`}</p></div>
            </div>
            {u.reason && <p className="mt-2 text-sm">{u.reason}</p>}
          </Link>
        ))}
      </div>
      <p className="mt-3 text-xs text-muted">
        Fans = fan sentiment 0-100. Perf. = performance percentile at his position among players fans discuss (5v5
        expected goals share, projected WAR, Game Score). Reasons are written by Claude from the numbers only.
      </p>
    </section>
  );
}

// Signed cap hits for this season and the next four (Brian, 2026-10-03). This season's total is the full cap
// charge (buried players, dead cap, and retained salary as charged today); later seasons add up the signed contracts,
// so they will rise as the team signs players.
function FutureCapGrid({ future, thisSeasonTotal }: {
  future: { seasons: number[]; rows: FutureCapRow[]; ceilings: Map<number, number> };
  thisSeasonTotal: number;
}) {
  const { seasons, rows, ceilings } = future;
  const groups: { title: string; rows: FutureCapRow[] }[] = [
    { title: "Forwards", rows: rows.filter((r) => !r.retained && !["D", "G"].includes(r.position)) },
    { title: "Defense", rows: rows.filter((r) => !r.retained && r.position === "D") },
    { title: "Goalies", rows: rows.filter((r) => !r.retained && r.position === "G") },
    { title: "Retained salary", rows: rows.filter((r) => r.retained) },
  ].filter((g) => g.rows.length);
  const sum = (s: number) => rows.reduce((t, r) => t + (r.by_season[String(s)] ?? 0), 0);
  const count = (s: number) => rows.filter((r) => !r.retained && r.by_season[String(s)] !== undefined).length;
  const committed = (s: number, i: number) => (i === 0 ? thisSeasonTotal : sum(s));
  const cell = "px-2 py-1.5 text-right font-mono";
  return (
    <section className="mt-6 overflow-x-auto rounded-lg border border-border bg-surface px-4 pb-4">
      <h2 className="pt-4 font-heading text-2xl font-semibold uppercase tracking-tight">Cap by season</h2>
      <p className="mt-1 text-xs text-muted">
        Signed cap hits by season. A badge marks the final season of each deal: UFA or RFA after it. Later seasons count only contracts
        signed so far.
      </p>
      <table className="mt-3 w-full min-w-max border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-xs font-semibold uppercase tracking-wide text-muted">
            <th className="sticky left-0 z-10 bg-surface py-2 pr-3 text-left">Player</th>
            {seasons.map((s) => <th key={s} className="px-2 py-2 text-right">{seasonLabel(s)}</th>)}
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <Fragment key={g.title}>
              <tr>
                <td colSpan={seasons.length + 1} className="sticky left-0 bg-surface pb-1 pt-4 text-xs font-semibold uppercase tracking-wide text-muted">{g.title}</td>
              </tr>
              {g.rows.map((r) => (
                <tr key={`${r.player_id ?? r.name}-${r.retained}`} className="border-b border-border-soft">
                  <td className="sticky left-0 z-10 bg-surface py-1.5 pr-3">
                    {r.player_id && !r.retained ? <Link href={`/player/${r.player_id}`} className="hover:underline">{r.name}</Link> : r.name}
                    {r.position && !r.retained && <span className="ml-1 text-xs text-muted">{r.position}</span>}
                    {r.clause && r.clause !== "none" && <span className="ml-1 text-[10px] font-semibold text-muted">{r.clause}</span>}
                  </td>
                  {seasons.map((s) => {
                    const v = r.by_season[String(s)];
                    const final = !r.retained && s === r.end_season;
                    return (
                      <td key={s} className={`${cell} ${v === undefined ? "text-border" : ""}`}>
                        {v === undefined ? "·" : v === null ? "unknown" : money(v)}
                        {final && r.expiry_status && (
                          <span className={`ml-1 rounded px-1 font-sans text-[10px] font-semibold ${r.expiry_status === "UFA" ? "bg-negative-soft text-negative" : "bg-border-soft text-muted"}`}>
                            {r.expiry_status}
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </Fragment>
          ))}
        </tbody>
        <tfoot className="text-sm">
          <tr className="border-t-2 border-border font-semibold">
            <td className="sticky left-0 z-10 bg-surface py-2 pr-3">Committed</td>
            {seasons.map((s, i) => <td key={s} className={cell}>{money(committed(s, i))}</td>)}
          </tr>
          <tr>
            <td className="sticky left-0 z-10 bg-surface py-1.5 pr-3 text-muted">Players signed</td>
            {seasons.map((s) => <td key={s} className={`${cell} text-muted`}>{count(s)}</td>)}
          </tr>
          <tr>
            <td className="sticky left-0 z-10 bg-surface py-1.5 pr-3 text-muted">Cap ceiling</td>
            {seasons.map((s) => <td key={s} className={`${cell} text-muted`}>{ceilings.has(s) ? money(ceilings.get(s)!) : "not set"}</td>)}
          </tr>
          <tr className="font-semibold">
            <td className="sticky left-0 z-10 bg-surface py-1.5 pr-3">Cap space</td>
            {seasons.map((s, i) => {
              const c = ceilings.get(s);
              const space = c == null ? null : c - committed(s, i);
              return (
                <td key={s} className={`${cell} ${space == null ? "text-muted" : space >= 0 ? "text-positive" : "text-negative"}`}>
                  {space == null ? "—" : money(space)}
                </td>
              );
            })}
          </tr>
        </tfoot>
      </table>
      <p className="mt-3 text-xs text-muted">
        This season&apos;s committed total is the full cap charge used above (players in the minors count only above the buried allowance,
        plus dead cap); before LTIR relief. The 2027-28 ceiling of $113.5M is the league&apos;s announced figure; later ceilings are not set
        yet. Buyouts and dead cap in future seasons are not included.
      </p>
    </section>
  );
}
