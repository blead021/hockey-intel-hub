import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import type { ReactNode } from "react";
import { PlayStyleSection } from "@/components/play-style";
import { DataTable, Panel, Td, Th, Unavailable } from "@/components/ui";
import { withDb } from "@/lib/db";
import { faceoffPct, heightFt, money, num, pct, season as seasonLabel, shortDate, signed, svPct, toi } from "@/lib/format";
import {
  getCapCeiling,
  getCurrentContract,
  getEnabledSources,
  getGameScoreBreakdown,
  getGoalieSeasons,
  getLatestEdge,
  getLatestOniceSeason,
  getPlayer,
  getPlayStyle,
  getSkaterAdvanced,
  getSkaterLastGames,
  getSkaterSeasons,
  getXgfBySeason,
  type Contract,
  type Edge,
  type GameScoreBreakdown,
  type GoalieSeason,
  type Player,
  type SkaterAdvanced,
  type SkaterGame,
  type SkaterSeason,
} from "@/lib/queries";
import { currentSeason } from "@/lib/seasons";

function parseId(value: string): number | null {
  return /^\d{7}$/.test(value) ? Number(value) : null;
}

export async function generateMetadata({ params }: PageProps<"/player/[id]">) {
  const id = parseId((await params).id);
  const player = id ? await withDb((sql) => getPlayer(sql, id)) : undefined;
  return { title: player ? `${player.first_name} ${player.last_name}` : "Player" };
}

const POSITIONS: Record<string, string> = { C: "Center", L: "Left wing", R: "Right wing", D: "Defense", G: "Goalie" };

export default async function PlayerPage({ params }: PageProps<"/player/[id]">) {
  await connection();
  const id = parseId((await params).id);
  if (!id) notFound();
  const season = currentSeason();

  const data = await withDb(async (sql) => {
    const player = await getPlayer(sql, id);
    if (!player) return null;
    const isGoalie = player.position === "G";
    const oniceSeason = isGoalie ? undefined : await getLatestOniceSeason(sql, id);
    const breakdownSeason = isGoalie
      ? (await sql<{ s: number | null }[]>`select max(g.season_id) as s from player_game_score gs join games g on g.id = gs.game_id where gs.player_id = ${id} and g.game_type = 2`)[0]?.s
      : oniceSeason;
    const [skaterSeasons, goalieSeasons, lastGames, contract, ceiling, edge, sources, advanced, breakdown, style, xgf] =
      await Promise.all([
        isGoalie ? Promise.resolve([]) : getSkaterSeasons(sql, id),
        isGoalie ? getGoalieSeasons(sql, id) : Promise.resolve([]),
        isGoalie ? Promise.resolve([]) : getSkaterLastGames(sql, id),
        getCurrentContract(sql, id, season),
        getCapCeiling(sql, season),
        isGoalie ? Promise.resolve(undefined) : getLatestEdge(sql, id),
        getEnabledSources(sql),
        oniceSeason ? getSkaterAdvanced(sql, id, oniceSeason) : Promise.resolve(undefined),
        breakdownSeason ? getGameScoreBreakdown(sql, id, breakdownSeason) : Promise.resolve(undefined),
        !isGoalie && oniceSeason ? getPlayStyle(sql, id, oniceSeason) : Promise.resolve(undefined),
        isGoalie ? Promise.resolve(new Map<number, number>()) : getXgfBySeason(sql, id),
      ]);
    return { player, isGoalie, skaterSeasons, goalieSeasons, lastGames, contract, ceiling, edge, sources, advanced, breakdown, style, xgf };
  });
  if (!data) notFound();
  const { player, isGoalie, skaterSeasons, goalieSeasons, lastGames, contract, ceiling, edge, sources, advanced, breakdown, style, xgf } = data;

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-8">
      <Header player={player} contract={sources.has("contracts_csv") ? contract : undefined} ceiling={ceiling} showContract={sources.has("contracts_csv")} />

      {isGoalie ? (
        <>
          <GoalieCards seasons={goalieSeasons} current={season} />
          <GoalieSeasons seasons={goalieSeasons} />
          <GameScorePanel breakdown={breakdown} />
        </>
      ) : (
        <>
          <SkaterCards seasons={skaterSeasons} current={season} xgf={xgf} />
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_26rem]">
            <div className="min-w-0 space-y-6">
              <GameLog games={lastGames} />
              <AdvancedPanel advanced={advanced} position={player.position} />
              <PlayStyleSection style={style} />
              <GameScorePanel breakdown={breakdown} />
              <SkaterSeasonsPanel seasons={skaterSeasons} />
            </div>
            <div className="min-w-0 space-y-6">
              <SentimentPanel />
              <Panel title="Age curve">
                <Unavailable>
                  How players at his position age, and where his contract falls on that curve, arrives with the trade tools.
                </Unavailable>
              </Panel>
              {sources.has("nhl_edge") && <SkatingPanel edge={edge} />}
            </div>
          </div>
        </>
      )}
    </main>
  );
}

function Header({ player, contract, ceiling, showContract }: { player: Player; contract: Contract | undefined; ceiling: number | null; showContract: boolean }) {
  const isGoalie = player.position === "G";
  const eyebrow = [
    player.team_name ?? "Not on an NHL roster",
    player.position ? POSITIONS[player.position] ?? player.position : null,
    player.shoots ? `${isGoalie ? "Catches" : "Shoots"} ${player.shoots}` : null,
  ].filter(Boolean);
  const bio = [
    player.age != null ? `Age ${player.age}` : null,
    player.height_in ? heightFt(player.height_in) : null,
    player.weight_lb ? `${player.weight_lb} lb` : null,
    player.birth_city ? `Born in ${player.birth_city}${player.birth_country ? `, ${player.birth_country}` : ""}` : null,
  ].filter(Boolean);
  return (
    <section className="flex flex-col gap-6 rounded-lg border border-border bg-surface p-5 xl:flex-row xl:items-center xl:justify-between">
      <div className="flex items-center gap-5">
        <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-lg bg-positive-soft font-mono text-3xl font-semibold text-positive">
          {player.number ?? "—"}
        </div>
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-widest text-muted">
            {player.team_abbrev ? (
              <Link href={`/team/${player.team_abbrev}`} className="hover:underline">{eyebrow[0]}</Link>
            ) : (
              eyebrow[0]
            )}
            {eyebrow.slice(1).map((e) => ` · ${e}`)}
          </p>
          <h1 className="font-heading text-4xl font-bold leading-tight tracking-tight sm:text-5xl">
            {player.first_name} {player.last_name}
          </h1>
          <p className="text-sm text-muted">{bio.join(" · ")}</p>
        </div>
      </div>
      {showContract && <ContractBoxes contract={contract} ceiling={ceiling} />}
    </section>
  );
}

function ContractBoxes({ contract, ceiling }: { contract: Contract | undefined; ceiling: number | null }) {
  if (!contract) return <p className="text-sm text-muted">No contract on file.</p>;
  const years = Math.floor(contract.end_season / 10000) - Math.floor(currentSeason() / 10000) + 1;
  // The cap hit charged to his team, after any share his previous team retained.
  const charged = contract.cap_hit * (1 - (contract.retained_pct ?? 0) / 100);
  const capDetail = contract.retained_pct > 0
    ? `${contract.retained_pct}% retained by previous team`
    : ceiling ? `${((charged / ceiling) * 100).toFixed(1)}% of ${money(ceiling)} cap` : undefined;
  const clause = contract.clause && contract.clause !== "none" ? contract.clause : "None";
  return (
    <div>
    <div className="grid grid-cols-2 overflow-hidden rounded-lg border border-border sm:grid-cols-4">
      <Box label="Cap hit" value={money(charged)} detail={capDetail} />
      <Box label="Term" value={`${years} yr${years === 1 ? "" : "s"}`} detail={`Through ${seasonLabel(contract.end_season)}${contract.expiry_status ? `, then ${contract.expiry_status}` : ""}`} />
      <Box label="Clause" value={clause} detail={contract.no_trade_list_size ? `${contract.no_trade_list_size}-team no-trade list` : undefined} />
      <Box label="Surplus value" value="—" detail="arrives with the trade tools" highlight />
    </div>
    <p className="mt-2 text-right text-xs text-muted">
      {contract.source_status === "confirmed" ? (
        <>
          Confirmed by the public signing announcement
          {contract.source_url && (
            <>
              {" · "}
              <a href={contract.source_url} target="_blank" rel="noopener noreferrer" className="underline">source</a>
            </>
          )}
        </>
      ) : (
        "Contract details from our records; public announcement not yet matched"
      )}
    </p>
    </div>
  );
}

function Box({ label, value, detail, highlight }: { label: string; value: ReactNode; detail?: ReactNode; highlight?: boolean }) {
  return (
    <div className={`border-border p-4 [&:not(:last-child)]:border-r ${highlight ? "bg-positive-soft" : ""}`}>
      <p className={`text-xs font-semibold uppercase tracking-wide ${highlight ? "text-positive" : "text-muted"}`}>{label}</p>
      <p className="mt-1 font-mono text-xl">{value}</p>
      {detail && <p className="mt-1 text-xs text-muted">{detail}</p>}
    </div>
  );
}

function Card({ label, value, detail }: { label: string; value: ReactNode; detail?: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1 font-mono text-2xl">{value}</p>
      {detail && <p className="mt-1 text-xs text-muted">{detail}</p>}
    </div>
  );
}

function SkaterCards({ seasons, current, xgf }: { seasons: SkaterSeason[]; current: number; xgf: Map<number, number> }) {
  const s = seasons.find((x) => x.season_id === current) ?? seasons[0];
  if (!s) return null;
  const xgfNow = xgf.get(s.season_id);
  const xgfLast = xgf.get(s.season_id - 10001);
  const xgfDetail = xgfNow != null && xgfLast != null
    ? `5v5, ${signed(Math.round((xgfNow - xgfLast) * 1000) / 10)} vs. last yr`
    : "5v5";
  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted">{seasonLabel(s.season_id)} regular season</p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-9">
        <Card label="GP" value={s.gp} />
        <Card label="Goals" value={s.g} detail={s.sog ? `${((s.g / s.sog) * 100).toFixed(1)}% shooting` : undefined} />
        <Card label="Assists" value={s.a} detail={`${s.a1} primary`} />
        <Card label="Points" value={s.pts} detail={s.gp ? `${num(s.pts / s.gp, 2)} per game` : undefined} />
        <Card
          label="TOI/GP"
          value={toi(s.toi_sec / s.gp)}
          detail={`PP ${s.pp_toi_sec != null ? toi(s.pp_toi_sec / s.gp) : "—"} · PK ${s.pk_toi_sec != null ? toi(s.pk_toi_sec / s.gp) : "—"}`}
        />
        <Card label="xGF%" value={xgfNow == null ? "—" : (xgfNow * 100).toFixed(1)} detail={xgfDetail} />
        <Card label="Game Score" value={signedNum(s.game_score)} detail="per game, goals above average" />
        <Card label="Faceoff %" value={faceoffPct(s.fow, s.fol).replace("%", "")} detail={s.fow + s.fol ? `${s.fow} W · ${s.fol} L` : undefined} />
        <Card label="Plus/minus" value={signed(s.plus_minus)} detail={`Blocks ${s.blocks} · Hits ${s.hits}`} />
      </div>
    </div>
  );
}

function GameLog({ games }: { games: SkaterGame[] }) {
  return (
    <Panel title="Game log" note="Last 5 games · NHL API">
      {games.length === 0 ? (
        <Unavailable>No games played yet.</Unavailable>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full min-w-max border-collapse text-sm">
              <thead>
                <tr className="border-b border-border text-xs font-semibold text-muted">
                  {["Game", "G", "A", "SOG", "HIT", "BLK", "TOI", "PP", "PK", "FO", "OZS%", "GV", "TK", "+/-", "GS"].map((h, i) => (
                    <th key={h} className={`py-2 ${i === 0 ? "pr-3 text-left" : "px-2 text-right"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="font-mono">
                {games.map((g) => {
                  const starts = (g.oz_starts ?? 0) + (g.dz_starts ?? 0);
                  return (
                    <tr key={g.game_id} className="border-b border-border-soft">
                      <td className="py-2 pr-3 text-left font-sans leading-tight">
                        {shortDate(g.game_date)}
                        <br />
                        <span className="text-xs text-muted">{g.home ? "vs" : "@"} {g.opponent} · {g.result}</span>
                      </td>
                      <td className="px-2 text-right">{g.g}</td>
                      <td className="px-2 text-right">{g.a}</td>
                      <td className="px-2 text-right">{g.sog}</td>
                      <td className="px-2 text-right">{g.hits}</td>
                      <td className="px-2 text-right">{g.blocks}</td>
                      <td className="px-2 text-right">{toi(g.toi_sec)}</td>
                      <td className="px-2 text-right">{g.pp_toi_sec != null ? toi(g.pp_toi_sec) : "—"}</td>
                      <td className="px-2 text-right">{g.pk_toi_sec != null ? toi(g.pk_toi_sec) : "—"}</td>
                      <td className="px-2 text-right">{g.fow + g.fol ? `${g.fow}-${g.fol}` : "—"}</td>
                      <td className="px-2 text-right">{starts ? Math.round(((g.oz_starts ?? 0) / starts) * 100) : "—"}</td>
                      <td className="px-2 text-right">{g.giveaways}</td>
                      <td className="px-2 text-right">{g.takeaways}</td>
                      <td className="px-2 text-right">{signed(g.plus_minus)}</td>
                      <td className={`px-2 text-right ${g.game_score == null ? "" : g.game_score >= 0 ? "text-positive" : "text-negative"}`}>
                        {signedNum(g.game_score)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-muted">
            GS = our Game Score, goals above average. FO = faceoffs won-lost. OZS% = share of his 5v5 offensive and
            defensive zone faceoff starts that were in the offensive zone. GV/TK = giveaways/takeaways.
          </p>
        </>
      )}
    </Panel>
  );
}

// Context stats describe a player's deployment or luck, not quality, so their bars are neutral.
const CONTEXT_METRICS = new Set(["PDO", "OZS%"]);

function formatMetric(key: string, value: number | null): string {
  if (value == null) return "—";
  if (key === "PDO") return num(value, 1);
  if (key === "ixG/60") return num(value, 2);
  if (key.endsWith("/60")) return num(value, 1);
  if (key === "Goals above expected") return `${value > 0 ? "+" : ""}${value.toFixed(1)}`;
  if (key.startsWith("Relative")) return `${value > 0 ? "+" : ""}${(value * 100).toFixed(1)}`;
  return pct(value);
}

function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
}

function AdvancedPanel({ advanced, position }: { advanced: SkaterAdvanced | undefined; position: string | null }) {
  const group = position === "D" ? "defensemen" : "forwards";
  return (
    <Panel
      title="Advanced metrics"
      note={advanced
        ? `5v5 unless noted · ${seasonLabel(advanced.season_id)} · ${Math.round(advanced.toi_5v5_sec / 60).toLocaleString("en-US")} min · percentile vs. NHL ${group}`
        : undefined}
    >
      {!advanced ? (
        <Unavailable>No 5v5 on-ice data yet.</Unavailable>
      ) : (
        <>
          {!advanced.ranked && <p className="mb-3 text-sm text-muted">Percentiles appear after 100 minutes at 5v5.</p>}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
            {advanced.metrics.map((m) => {
              const rank = m.pctile == null ? null : Math.round(m.pctile * 100);
              const fill = CONTEXT_METRICS.has(m.key) ? "bg-muted" : rank != null && rank >= 50 ? "bg-positive" : "bg-negative";
              return (
                <div key={m.key} className="rounded-lg border border-border p-3">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-xs font-semibold">{m.key}</span>
                    <span className="font-mono text-lg">{formatMetric(m.key, m.value)}</span>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-border-soft" aria-hidden>
                    {rank != null && <div className={`h-full ${fill}`} style={{ width: `${Math.max(rank, 2)}%` }} />}
                  </div>
                  <p className="mt-1 text-xs text-muted">{rank == null ? "no percentile yet" : `${ordinal(rank)} percentile`}</p>
                </div>
              );
            })}
          </div>
          <p className="mt-4 text-xs text-muted">
            xGF% is his team&apos;s share of 5v5 expected goals while he was on the ice, from our own expected goals model;
            HDCF% counts only high-danger chances (xG of 0.15 or more). IPP is the share of his team&apos;s 5v5 goals while
            he was on the ice that he scored or assisted on. Relative stats compare him with his team when he was off the
            ice. Goals above expected and ixG/60 use his own shots at all strengths. PDO and OZS% describe luck and
            deployment, so their bars are grey.
          </p>
        </>
      )}
    </Panel>
  );
}

function signedNum(value: number | null | undefined, digits = 2): string {
  if (value == null) return "—";
  const text = value.toFixed(digits);
  return value > 0 ? `+${text}` : text;
}

function GameScorePanel({ breakdown }: { breakdown: GameScoreBreakdown | undefined }) {
  if (!breakdown) return null;
  const largest = Math.max(...breakdown.parts.map((p) => Math.abs(p.value)), 0.01);
  return (
    <Panel title="Where his Game Score comes from" note={`${seasonLabel(breakdown.season_id)} · ${breakdown.gp} GP · goals above average`}>
      <p className="mb-4 text-sm">
        Season total <span className="font-mono font-medium">{signedNum(breakdown.total, 1)}</span> goals, or{" "}
        <span className="font-mono font-medium">{signedNum(breakdown.per_game)}</span> per game.
      </p>
      <dl className="space-y-2">
        {breakdown.parts.map((p) => (
          <div key={p.key} className="grid grid-cols-[10rem_4rem_1fr] items-center gap-3">
            <dt className="text-sm text-muted">{p.key}</dt>
            <dd className="text-right font-mono text-sm">{signedNum(p.value, 1)}</dd>
            <dd className="flex h-2 items-center" aria-hidden>
              <div
                className={`h-2 rounded-full ${p.value >= 0 ? "bg-positive" : "bg-negative"}`}
                style={{ width: `${Math.max((Math.abs(p.value) / largest) * 100, 2)}%` }}
              />
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-4 text-xs text-muted">
        Game Score adds up a player&apos;s impact in goals compared with an average player given the same ice time: his
        share of expected goals for and against at even strength, on the power play, and on the penalty kill, plus
        finishing (goals minus expected goals), primary assists, penalties drawn and taken, and faceoffs. Goalies are
        measured by goals saved above expected.
      </p>
    </Panel>
  );
}

function SkaterSeasonsPanel({ seasons }: { seasons: SkaterSeason[] }) {
  return (
    <Panel title="By season" note="Regular season">
      {seasons.length === 0 ? (
        <Unavailable>No NHL games in our data yet.</Unavailable>
      ) : (
        <DataTable>
          <thead>
            <tr>
              {["Team", "GP", "G", "A", "P", "+/-", "SOG", "TOI/GP", "FO%", "GS/GP"].reduce<ReactNode[]>(
                (acc, h) => [...acc, <Th key={h}>{h}</Th>],
                [<Th key="Season" left>Season</Th>],
              )}
            </tr>
          </thead>
          <tbody>
            {seasons.map((s) => (
              <tr key={s.season_id}>
                <Td left>{seasonLabel(s.season_id)}</Td>
                <Td>{s.teams}</Td>
                <Td>{s.gp}</Td>
                <Td>{s.g}</Td>
                <Td>{s.a}</Td>
                <Td>{s.pts}</Td>
                <Td>{signed(s.plus_minus)}</Td>
                <Td>{s.sog}</Td>
                <Td>{toi(s.toi_sec / s.gp)}</Td>
                <Td>{faceoffPct(s.fow, s.fol)}</Td>
                <Td>{signedNum(s.game_score)}</Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </Panel>
  );
}

function SentimentPanel() {
  return (
    <Panel title="Sentiment & chatter">
      <div className="grid grid-cols-3 gap-2">
        {["Fans", "Beat writers", "Media"].map((a) => (
          <div key={a} className="rounded-lg border border-border p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">{a}</p>
            <p className="mt-1 font-mono text-2xl">—</p>
          </div>
        ))}
      </div>
      <p className="mt-4 text-sm text-muted">
        Fan, beat writer, and media scores, the 14-day trade chatter chart, and the latest mentions appear once
        sentiment scoring is switched on. Mentions are already being collected.
      </p>
    </Panel>
  );
}

function SkatingPanel({ edge }: { edge: Edge | undefined }) {
  const pctile = (v: number | null) => (v == null ? undefined : `${ordinal(Math.round(v * 100))} pct`);
  return (
    <Panel title="Skating · NHL EDGE" note={edge ? `${seasonLabel(edge.season_id)}, as of ${shortDate(edge.as_of)}` : undefined}>
      {!edge ? (
        <Unavailable>No NHL EDGE data yet. It refreshes weekly.</Unavailable>
      ) : (
        <dl className="grid grid-cols-3 gap-4">
          <Stat label="Top speed" value={edge.top_speed_mph ? `${num(edge.top_speed_mph, 1)} mph` : "—"} detail={pctile(edge.top_speed_pctile)} />
          <Stat label="20+ mph bursts" value={num(edge.bursts_20plus)} />
          <Stat label="Hardest shot" value={edge.max_shot_speed_mph ? `${num(edge.max_shot_speed_mph, 1)} mph` : "—"} detail={pctile(edge.max_shot_speed_pctile)} />
          <Stat label="Distance" value={edge.distance_skated_mi ? `${num(edge.distance_skated_mi, 1)} mi` : "—"} />
          <Stat label="OZ time" value={pct(edge.oz_time_pct)} detail={pctile(edge.oz_time_pctile)} />
          <Stat label="DZ time" value={pct(edge.dz_time_pct)} />
        </dl>
      )}
    </Panel>
  );
}

function Stat({ label, value, detail }: { label: string; value: ReactNode; detail?: string }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="font-mono text-lg">{value}</dd>
      {detail && <dd className="text-xs text-muted">{detail}</dd>}
    </div>
  );
}

function GoalieCards({ seasons, current }: { seasons: GoalieSeason[]; current: number }) {
  const s = seasons.find((x) => x.season_id === current) ?? seasons[0];
  if (!s) return null;
  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted">{seasonLabel(s.season_id)} regular season</p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
        <Card label="GP" value={s.gp} detail={`${s.gs} starts`} />
        <Card label="Record" value={`${s.w}-${s.l}-${s.otl}`} />
        <Card label="SV%" value={svPct(s.saves, s.shots_against)} />
        <Card label="GAA" value={s.toi_sec ? num((s.ga * 3600) / s.toi_sec, 2) : "—"} />
        <Card label="Shots against" value={s.shots_against} />
        <Card label="GSAx" value={s.gsax == null ? "—" : signed(Math.round(s.gsax * 10) / 10)} detail="goals saved above expected" />
        <Card label="Game Score" value={signedNum(s.game_score)} detail="per game" />
      </div>
    </div>
  );
}

function GoalieSeasons({ seasons }: { seasons: GoalieSeason[] }) {
  return (
    <Panel title="By season" note="Regular season">
      {seasons.length === 0 ? (
        <Unavailable>No NHL games in our data yet.</Unavailable>
      ) : (
        <DataTable>
          <thead>
            <tr>
              <Th left>Season</Th>
              <Th>Team</Th>
              <Th>GP</Th>
              <Th>GS</Th>
              <Th>W-L-OTL</Th>
              <Th>SV%</Th>
              <Th>GAA</Th>
              <Th>SA</Th>
              <Th>GSAx</Th>
            </tr>
          </thead>
          <tbody>
            {seasons.map((g) => (
              <tr key={g.season_id}>
                <Td left>{seasonLabel(g.season_id)}</Td>
                <Td>{g.teams}</Td>
                <Td>{g.gp}</Td>
                <Td>{g.gs}</Td>
                <Td>{`${g.w}-${g.l}-${g.otl}`}</Td>
                <Td>{svPct(g.saves, g.shots_against)}</Td>
                <Td>{g.toi_sec ? num((g.ga * 3600) / g.toi_sec, 2) : "—"}</Td>
                <Td>{g.shots_against}</Td>
                <Td>{g.gsax == null ? "—" : signed(Math.round(g.gsax * 10) / 10)}</Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </Panel>
  );
}
