import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { CardGrid, DataTable, PageTitle, SectionTitle, StatCard, Td, Th, Unavailable } from "@/components/ui";
import { withDb } from "@/lib/db";
import { faceoffPct, heightFt, money, num, pct, season as seasonLabel, shortDate, signed, svPct, toi } from "@/lib/format";
import {
  getCurrentContract,
  getEnabledSources,
  getLatestOniceSeason,
  getSkaterAdvanced,
  getGoalieSeasons,
  getLatestEdge,
  getPlayer,
  getSkaterLastGames,
  getSkaterSeasons,
  type Edge,
  type GoalieSeason,
  type SkaterAdvanced,
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
    const [skaterSeasons, goalieSeasons, lastGames, contract, edge, sources, advanced] = await Promise.all([
      isGoalie ? Promise.resolve([]) : getSkaterSeasons(sql, id),
      isGoalie ? getGoalieSeasons(sql, id) : Promise.resolve([]),
      isGoalie ? Promise.resolve([]) : getSkaterLastGames(sql, id),
      getCurrentContract(sql, id, season),
      isGoalie ? Promise.resolve(undefined) : getLatestEdge(sql, id),
      getEnabledSources(sql),
      oniceSeason ? getSkaterAdvanced(sql, id, oniceSeason) : Promise.resolve(undefined),
    ]);
    return { player, isGoalie, skaterSeasons, goalieSeasons, lastGames, contract, edge, sources, advanced };
  });
  if (!data) notFound();
  const { player, isGoalie, skaterSeasons, goalieSeasons, lastGames, contract, edge, sources, advanced } = data;

  const bio = [
    player.position,
    player.shoots ? `${isGoalie ? "Catches" : "Shoots"} ${player.shoots}` : null,
    player.height_in ? heightFt(player.height_in) : null,
    player.weight_lb ? `${player.weight_lb} lb` : null,
    player.age != null ? `Age ${player.age}` : null,
  ].filter(Boolean);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
        {player.headshot_url && (
          // NHL headshots are served as-is; Cloudflare image optimization is off to avoid its fees.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={player.headshot_url}
            alt=""
            width={112}
            height={112}
            className="h-28 w-28 rounded-full border border-border bg-surface object-cover"
          />
        )}
        <PageTitle
          eyebrow={
            player.team_abbrev ? (
              <Link href={`/team/${player.team_abbrev}`} className="hover:underline">
                {player.team_name}
                {player.number != null ? ` · #${player.number}` : ""}
              </Link>
            ) : (
              "Not on an NHL roster"
            )
          }
          title={`${player.first_name} ${player.last_name}`}
        >
          <p className="mt-1 text-sm text-muted">{bio.join(" · ")}</p>
        </PageTitle>
      </div>

      {sources.has("contracts_csv") && (
        <div className="mt-6">
          <ContractStrip contract={contract} />
        </div>
      )}

      {isGoalie ? (
        <GoalieSections seasons={goalieSeasons} current={season} />
      ) : (
        <>
          <SkaterCards seasons={skaterSeasons} current={season} />

          <SectionTitle note="Most recent first">Last 5 games</SectionTitle>
          {lastGames.length === 0 ? (
            <Unavailable>No games played yet.</Unavailable>
          ) : (
            <DataTable>
              <thead>
                <tr>
                  <Th left>Date</Th>
                  <Th>Opp</Th>
                  <Th>Result</Th>
                  <Th>G</Th>
                  <Th>A</Th>
                  <Th>P</Th>
                  <Th>+/-</Th>
                  <Th>SOG</Th>
                  <Th>TOI</Th>
                  <Th>FO W-L</Th>
                  <Th>Game Score</Th>
                </tr>
              </thead>
              <tbody>
                {lastGames.map((g) => (
                  <tr key={g.game_id}>
                    <Td left>{shortDate(g.game_date)}</Td>
                    <Td>{`${g.home ? "vs" : "@"} ${g.opponent}`}</Td>
                    <Td>{g.result}</Td>
                    <Td>{g.g}</Td>
                    <Td>{g.a}</Td>
                    <Td>{g.pts}</Td>
                    <Td>{signed(g.plus_minus)}</Td>
                    <Td>{g.sog}</Td>
                    <Td>{toi(g.toi_sec)}</Td>
                    <Td>{g.fow + g.fol ? `${g.fow}-${g.fol}` : "—"}</Td>
                    <Td>{num(g.game_score, 2)}</Td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          )}

          <SectionTitle note="Regular season">By season</SectionTitle>
          {skaterSeasons.length === 0 ? (
            <Unavailable>No NHL games in our data yet.</Unavailable>
          ) : (
            <DataTable>
              <thead>
                <tr>
                  <Th left>Season</Th>
                  <Th>Team</Th>
                  <Th>GP</Th>
                  <Th>G</Th>
                  <Th>A</Th>
                  <Th>P</Th>
                  <Th>Prim. P</Th>
                  <Th>+/-</Th>
                  <Th>SOG</Th>
                  <Th>Hits</Th>
                  <Th>Blk</Th>
                  <Th>TOI/GP</Th>
                  <Th>PP TOI/GP</Th>
                  <Th>PK TOI/GP</Th>
                  <Th>FO%</Th>
                </tr>
              </thead>
              <tbody>
                {skaterSeasons.map((s) => (
                  <tr key={s.season_id}>
                    <Td left>{seasonLabel(s.season_id)}</Td>
                    <Td>{s.teams}</Td>
                    <Td>{s.gp}</Td>
                    <Td>{s.g}</Td>
                    <Td>{s.a}</Td>
                    <Td>{s.pts}</Td>
                    <Td>{s.g + s.a1}</Td>
                    <Td>{signed(s.plus_minus)}</Td>
                    <Td>{s.sog}</Td>
                    <Td>{s.hits}</Td>
                    <Td>{s.blocks}</Td>
                    <Td>{toi(s.toi_sec / s.gp)}</Td>
                    <Td>{s.pp_toi_sec != null ? toi(s.pp_toi_sec / s.gp) : "—"}</Td>
                    <Td>{s.pk_toi_sec != null ? toi(s.pk_toi_sec / s.gp) : "—"}</Td>
                    <Td>{faceoffPct(s.fow, s.fol)}</Td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          )}

          <AdvancedSection advanced={advanced} position={player.position} />

          {sources.has("nhl_edge") && <EdgeSection edge={edge} />}
        </>
      )}

      <SectionTitle>More coming</SectionTitle>
      <Unavailable>Expected goals, WAR, surplus value, and fan and media sentiment are added in later phases.</Unavailable>
    </main>
  );
}

function ContractStrip({ contract }: { contract: Awaited<ReturnType<typeof getCurrentContract>> }) {
  if (!contract) {
    return <p className="text-sm text-muted">No contract on file.</p>;
  }
  const years = Math.floor(contract.end_season / 10000) - Math.floor(currentSeason() / 10000) + 1;
  return (
    <CardGrid>
      <StatCard label="Cap hit" value={money(contract.cap_hit)} />
      <StatCard label="Term left" value={`${years} yr${years === 1 ? "" : "s"}`} detail={`through ${seasonLabel(contract.end_season)}`} />
      <StatCard label="Expiry" value={contract.expiry_status ?? "—"} />
      <StatCard
        label="Clause"
        value={contract.clause && contract.clause !== "none" ? contract.clause : "None"}
        detail={contract.no_trade_list_size ? `${contract.no_trade_list_size}-team list` : undefined}
      />
      {contract.retained_pct > 0 && <StatCard label="Retained" value={`${contract.retained_pct}%`} />}
    </CardGrid>
  );
}

function SkaterCards({ seasons, current }: { seasons: SkaterSeason[]; current: number }) {
  const s = seasons.find((x) => x.season_id === current) ?? seasons[0];
  if (!s) return null;
  return (
    <>
      <SectionTitle>{seasonLabel(s.season_id)} season</SectionTitle>
      <CardGrid>
        <StatCard label="Games" value={s.gp} />
        <StatCard label="Goals" value={s.g} />
        <StatCard label="Assists" value={s.a} detail={`${s.a1} primary`} />
        <StatCard label="Points" value={s.pts} detail={s.gp ? `${num(s.pts / s.gp, 2)} per game` : undefined} />
        <StatCard label="TOI / GP" value={toi(s.toi_sec / s.gp)} />
        <StatCard label="Faceoff %" value={faceoffPct(s.fow, s.fol)} detail={`${s.fow}-${s.fol}`} />
        <StatCard label="Game Score" value={num(s.game_score, 2)} detail="average per game" />
      </CardGrid>
    </>
  );
}

function GoalieSections({ seasons, current }: { seasons: GoalieSeason[]; current: number }) {
  const s = seasons.find((x) => x.season_id === current) ?? seasons[0];
  return (
    <>
      {s && (
        <>
          <SectionTitle>{seasonLabel(s.season_id)} season</SectionTitle>
          <CardGrid>
            <StatCard label="Games" value={s.gp} detail={`${s.gs} starts`} />
            <StatCard label="Record" value={`${s.w}-${s.l}-${s.otl}`} />
            <StatCard label="SV%" value={svPct(s.saves, s.shots_against)} />
            <StatCard label="GAA" value={s.toi_sec ? num((s.ga * 3600) / s.toi_sec, 2) : "—"} />
            <StatCard label="Shots against" value={s.shots_against} />
            <StatCard label="GSAx" value={s.gsax == null ? "—" : signed(Math.round(s.gsax * 10) / 10)} detail="goals saved above expected" />
            <StatCard label="Game Score" value={num(s.game_score, 2)} detail="average per game" />
          </CardGrid>
        </>
      )}
      <SectionTitle note="Regular season">By season</SectionTitle>
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
    </>
  );
}

function EdgeSection({ edge }: { edge: Edge | undefined }) {
  return (
    <>
      <SectionTitle note={edge ? `NHL EDGE, ${seasonLabel(edge.season_id)}, as of ${shortDate(edge.as_of)}` : undefined}>
        Skating and shot tracking
      </SectionTitle>
      {!edge ? (
        <Unavailable>No NHL EDGE data yet. It refreshes weekly.</Unavailable>
      ) : (
        <CardGrid>
          <StatCard label="Top speed" value={edge.top_speed_mph ? `${num(edge.top_speed_mph, 1)} mph` : "—"} detail={pctile(edge.top_speed_pctile)} />
          <StatCard label="Bursts 20+ mph" value={num(edge.bursts_20plus)} />
          <StatCard label="Hardest shot" value={edge.max_shot_speed_mph ? `${num(edge.max_shot_speed_mph, 1)} mph` : "—"} detail={pctile(edge.max_shot_speed_pctile)} />
          <StatCard label="Distance skated" value={edge.distance_skated_mi ? `${num(edge.distance_skated_mi, 1)} mi` : "—"} />
          <StatCard label="Offensive zone time" value={pct(edge.oz_time_pct)} detail={pctile(edge.oz_time_pctile)} />
          <StatCard label="Defensive zone time" value={pct(edge.dz_time_pct)} />
        </CardGrid>
      )}
    </>
  );
}

function pctile(value: number | null): string | undefined {
  return value == null ? undefined : `${Math.round(value * 100)}th percentile`;
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

function AdvancedSection({ advanced, position }: { advanced: SkaterAdvanced | undefined; position: string | null }) {
  const group = position === "D" ? "defensemen" : "forwards";
  return (
    <>
      <SectionTitle
        note={
          advanced
            ? `5v5, ${seasonLabel(advanced.season_id)} · ${Math.round(advanced.toi_5v5_sec / 60).toLocaleString("en-US")} min in ${advanced.gp} GP · percentile vs. ${group}`
            : undefined
        }
      >
        Advanced metrics
      </SectionTitle>
      {!advanced ? (
        <Unavailable>No 5v5 on-ice data yet.</Unavailable>
      ) : (
        <div className="rounded-lg border border-border bg-surface p-4">
          {!advanced.ranked && (
            <p className="mb-3 text-sm text-muted">Percentiles appear after 100 minutes at 5v5.</p>
          )}
          <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
            {advanced.metrics.map((m) => (
              <div key={m.key} className="grid grid-cols-[7.5rem_4.5rem_1fr] items-center gap-3">
                <dt className="text-sm text-muted">{m.key}</dt>
                <dd className="text-right font-mono">{formatMetric(m.key, m.value)}</dd>
                <dd>
                  <PercentileBar value={m.pctile} neutral={CONTEXT_METRICS.has(m.key)} />
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-4 text-xs text-muted">
            xGF% is his team&apos;s share of 5v5 expected goals while he was on the ice, from our own expected goals model;
            HDCF% counts only high-danger chances (xG of 0.15 or more). CF% is the share of shot attempts; relative
            stats compare him with his team when he was off the ice. Goals above expected and ixG/60 use his own shots
            at all strengths. A shot blocked by a teammate counts as an attempt by the shooter&apos;s team.
          </p>
        </div>
      )}
    </>
  );
}

function PercentileBar({ value, neutral }: { value: number | null; neutral: boolean }) {
  if (value == null) return <span className="text-xs text-muted">—</span>;
  const rank = Math.round(value * 100);
  // Colors back up the number, which is always shown, so meaning never depends on color alone.
  const fill = neutral ? "bg-muted" : rank >= 50 ? "bg-positive" : "bg-negative";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-border-soft" aria-hidden>
        <div className={`h-full ${fill}`} style={{ width: `${Math.max(rank, 2)}%` }} />
      </div>
      <span className="w-8 text-right font-mono text-xs text-muted">{rank}</span>
    </div>
  );
}
