import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { CardGrid, DataTable, PageTitle, SeasonPicker, SectionTitle, StatCard, Td, Th, Unavailable } from "@/components/ui";
import { withDb } from "@/lib/db";
import { faceoffPct, money, num, pct, season as seasonLabel, signed, svPct, toi } from "@/lib/format";
import {
  getCapCeiling,
  getEnabledSources,
  getLoadedSeasons,
  getRosterGoalies,
  getRosterSkaters,
  getTeam,
  getTeamRecord,
  getTeamXgfPct,
  type RosterSkater,
} from "@/lib/queries";
import { currentSeason, parseSeason } from "@/lib/seasons";

export async function generateMetadata({ params }: PageProps<"/team/[abbrev]">) {
  const { abbrev } = await params;
  return { title: `${abbrev.toUpperCase()} roster` };
}

export default async function TeamPage({ params, searchParams }: PageProps<"/team/[abbrev]">) {
  await connection();
  const { abbrev } = await params;
  const requested = parseSeason((await searchParams).season);
  const current = currentSeason();

  const data = await withDb(async (sql) => {
    const team = await getTeam(sql, abbrev);
    if (!team) return null;
    const seasons = await getLoadedSeasons(sql);
    const season = requested ?? current;
    const isCurrent = season === current;
    const [record, skaters, goalies, sources, ceiling, xgfPct] = await Promise.all([
      getTeamRecord(sql, team.id, season),
      getRosterSkaters(sql, team.id, season, isCurrent),
      getRosterGoalies(sql, team.id, season, isCurrent),
      getEnabledSources(sql),
      getCapCeiling(sql, season),
      getTeamXgfPct(sql, team.id, season),
    ]);
    return { team, seasons, season, isCurrent, record, skaters, goalies, sources, ceiling, xgfPct };
  });
  if (!data) notFound();
  const { team, seasons, season, isCurrent, record, skaters, goalies, sources, ceiling, xgfPct } = data;

  const showContracts = sources.has("contracts_csv");
  const forwards = skaters.filter((s) => s.position !== "D");
  const defense = skaters.filter((s) => s.position === "D");
  const capCommitted = [...skaters, ...goalies].reduce((sum, p) => sum + (p.cap_hit ?? 0), 0);
  const hasContracts = [...skaters, ...goalies].some((p) => p.cap_hit != null);
  const pickerSeasons = [...new Set([current, ...seasons])].sort((a, b) => b - a);

  return (
    <main className="mx-auto max-w-7xl px-4 py-8">
      <PageTitle eyebrow={[team.conference, team.division].filter(Boolean).join(" · ")} title={team.name}>
        <SeasonPicker seasons={pickerSeasons} current={season} hrefFor={(s) => `/team/${team.abbrev}?season=${s}`} />
      </PageTitle>

      <CardGrid>
        <StatCard label="Record" value={`${record.w}-${record.l}-${record.otl}`} detail={`${record.gp} GP · ${seasonLabel(season)}`} />
        <StatCard label="Goals for / against" value={`${record.gf}-${record.ga}`} detail={`${signed(record.gf - record.ga)} differential`} />
        <StatCard label="Roster" value={skaters.length + goalies.length} detail={isCurrent ? "current roster" : "played this season"} />
        {showContracts && (
          <>
            <StatCard label="Cap committed" value={hasContracts ? money(capCommitted) : "—"} detail={hasContracts ? undefined : "no contracts loaded yet"} />
            <StatCard
              label="Cap space"
              value={hasContracts && ceiling ? money(ceiling - capCommitted) : "—"}
              detail={ceiling ? `ceiling ${money(ceiling)}` : "ceiling not set for this season"}
            />
          </>
        )}
        <StatCard label="5v5 xGF%" value={pct(xgfPct)} detail="share of expected goals at 5v5" />
      </CardGrid>

      <SkaterTable title="Forwards" rows={forwards} showContracts={showContracts} showFaceoffs />
      <SkaterTable title="Defense" rows={defense} showContracts={showContracts} />

      <SectionTitle>Goalies</SectionTitle>
      {goalies.length === 0 ? (
        <Unavailable>No goalies yet for this season.</Unavailable>
      ) : (
        <DataTable>
          <thead>
            <tr>
              <Th left>Goalie</Th>
              <Th>Age</Th>
              <Th>GP</Th>
              <Th>GS</Th>
              <Th>W-L-OTL</Th>
              <Th>SV%</Th>
              <Th>GAA</Th>
              <Th>SA</Th>
              <Th>GSAx</Th>
              {showContracts && <Th>Cap hit</Th>}
              {showContracts && <Th>Expiry</Th>}
            </tr>
          </thead>
          <tbody>
            {goalies.map((g) => (
              <tr key={g.id}>
                <Td left>
                  <PlayerLink id={g.id} name={g.name} number={g.number} />
                </Td>
                <Td>{num(g.age)}</Td>
                <Td>{g.gp}</Td>
                <Td>{g.gs}</Td>
                <Td>{`${g.w}-${g.l}-${g.otl}`}</Td>
                <Td>{svPct(g.saves, g.shots_against)}</Td>
                <Td>{g.toi_sec ? num((g.ga * 3600) / g.toi_sec, 2) : "—"}</Td>
                <Td>{g.shots_against}</Td>
                <Td>{g.gsax == null ? "—" : signed(Math.round(g.gsax * 10) / 10)}</Td>
                {showContracts && <Td>{money(g.cap_hit)}</Td>}
                {showContracts && <Td>{expiry(g.end_season, g.expiry_status)}</Td>}
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
      {!showContracts && (
        <p className="mt-6 text-sm text-muted">Contract data is unavailable right now.</p>
      )}
    </main>
  );
}

function PlayerLink({ id, name, number }: { id: number; name: string; number: number | null }) {
  return (
    <Link href={`/player/${id}`} className="font-medium hover:underline">
      {number != null && <span className="mr-2 inline-block w-6 font-mono text-xs text-muted">{number}</span>}
      {name}
    </Link>
  );
}

function expiry(endSeason: number | null, status: string | null): string {
  if (!endSeason) return "—";
  return `${Math.floor(endSeason / 10000) + 1}${status ? ` ${status}` : ""}`;
}

function SkaterTable({
  title,
  rows,
  showContracts,
  showFaceoffs = false,
}: {
  title: string;
  rows: RosterSkater[];
  showContracts: boolean;
  showFaceoffs?: boolean;
}) {
  return (
    <>
      <SectionTitle note={showFaceoffs ? "FO% shown for players with 50+ draws" : undefined}>{title}</SectionTitle>
      {rows.length === 0 ? (
        <Unavailable>No players yet for this season.</Unavailable>
      ) : (
        <DataTable>
          <thead>
            <tr>
              <Th left>Player</Th>
              <Th>Pos</Th>
              <Th>Age</Th>
              <Th>GP</Th>
              <Th>G</Th>
              <Th>A</Th>
              <Th>P</Th>
              <Th>+/-</Th>
              <Th>SOG</Th>
              <Th>TOI/GP</Th>
              <Th>PP TOI/GP</Th>
              <Th>5v5 xGF%</Th>
              {showFaceoffs && <Th>FO%</Th>}
              {showContracts && <Th>Cap hit</Th>}
              {showContracts && <Th>Expiry</Th>}
              {showContracts && <Th>Clause</Th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id}>
                <Td left>
                  <PlayerLink id={p.id} name={p.name} number={p.number} />
                </Td>
                <Td>{p.position}</Td>
                <Td>{num(p.age)}</Td>
                <Td>{p.gp}</Td>
                <Td>{p.g}</Td>
                <Td>{p.a}</Td>
                <Td>{p.pts}</Td>
                <Td>{signed(p.plus_minus)}</Td>
                <Td>{p.sog}</Td>
                <Td>{p.gp ? toi(p.toi_sec / p.gp) : "—"}</Td>
                <Td>{p.gp && p.pp_toi_sec != null ? toi(p.pp_toi_sec / p.gp) : "—"}</Td>
                <Td>{pct(p.xgf_pct)}</Td>
                {showFaceoffs && <Td>{p.position === "C" ? faceoffPct(p.fow, p.fol) : "—"}</Td>}
                {showContracts && <Td>{money(p.cap_hit)}</Td>}
                {showContracts && <Td>{expiry(p.end_season, p.expiry_status)}</Td>}
                {showContracts && <Td>{p.clause && p.clause !== "none" ? p.clause : "—"}</Td>}
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </>
  );
}
