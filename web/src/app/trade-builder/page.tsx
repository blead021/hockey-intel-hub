import { Locked } from "@/components/locked";
import { can } from "@/lib/access";
import { currentAccess } from "@/lib/session";
import { connection } from "next/server";
import { TradeBuilder, type Suggestion } from "@/components/trade-builder";
import { withDb } from "@/lib/db";
import { availability, needFit } from "@/lib/needs";
import { getAgingCurve, getBuilderTeam, getComparableTrades, getTeamBuyingPower, getTeams, getTradeTargets } from "@/lib/queries";
import { currentSeason } from "@/lib/seasons";

export const metadata = { title: "Trade Builder" };

type Params = Record<string, string | string[] | undefined>;
const one = (p: Params, k: string) => (typeof p[k] === "string" ? (p[k] as string) : undefined);

export default async function TradeBuilderPage({ searchParams }: PageProps<"/trade-builder">) {
  await connection();
  if (!can(await withDb(currentAccess), "trade_builder")) return <Locked eyebrow="Pro" title="Trade Builder" what="the Trade Builder" />;
  const p = (await searchParams) as Params;
  const season = currentSeason();
  const a = one(p, "a")?.toUpperCase();
  const b = one(p, "b")?.toUpperCase();

  const data = await withDb(async (sql) => {
    const [teams, teamA, teamB, curveF, curveD, curveG] = await Promise.all([
      getTeams(sql),
      a ? getBuilderTeam(sql, a, season) : Promise.resolve(undefined),
      b && b !== a ? getBuilderTeam(sql, b, season) : Promise.resolve(undefined),
      getAgingCurve(sql, "F"), getAgingCurve(sql, "D"), getAgingCurve(sql, "G"),
    ]);
    // Suggested targets for your team: players who fill its needs, weighted by how likely their team is to deal.
    let suggestions: Suggestion[] = [];
    if (teamA) {
      const [power, targets] = await Promise.all([
        getTeamBuyingPower(sql, teamA.id),
        getTradeTargets(sql, season, { exceptTeamId: teamA.id, group: "FD" }),
      ]);
      const goalieNeed = power.needs.some((n) => n.category === "goaltending");
      const pool = goalieNeed ? [...targets, ...(await getTradeTargets(sql, season, { exceptTeamId: teamA.id, group: "G" }))] : targets;
      suggestions = pool
        .map((t) => ({ t, fill: needFit(t, power.needs), score: (needFit(t, power.needs)?.score ?? 0) * availability(t) }))
        .filter((x) => x.fill && x.fill.pctile >= 70)
        .sort((x, y) => y.score - x.score)
        .slice(0, 8)
        .map(({ t, fill }) => ({
          id: t.player_id, name: t.name, team: t.team, position: t.position, age: t.age, cap_hit: t.cap_hit, years: t.years,
          war_proj: t.war_proj, category: fill!.category, pctile: fill!.pctile, team_status: t.team_status, chatter: t.chatter,
        }));
    }
    // Comparable past trades for the players in the deal (both directions), closest first, one entry per trade.
    const dealIds = ["in", "out"].flatMap((k) => (one(p, k) ?? "").split(",").filter(Boolean).map(Number)).filter((n) => n > 0);
    const seen = new Set<number>();
    const comparables = (await getComparableTrades(sql, dealIds)).filter((c) => !seen.has(c.trade_id) && seen.add(c.trade_id)).slice(0, 6);
    return { teams, teamA, teamB, curves: { F: curveF, D: curveD, G: curveG }, suggestions, comparables };
  });

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-8">
      <TradeBuilder
        key={JSON.stringify(p)}
        teams={data.teams.map((t) => ({ abbrev: t.abbrev, name: t.name }))}
        teamA={data.teamA}
        teamB={data.teamB}
        curves={data.curves}
        suggestions={data.suggestions}
        comparables={data.comparables}
        season={season}
        initial={{
          a: data.teamA?.abbrev ?? "", b: data.teamB?.abbrev ?? "",
          in: (one(p, "in") ?? "").split(",").filter(Boolean).map(Number),
          out: (one(p, "out") ?? "").split(",").filter(Boolean).map(Number),
          pin: (one(p, "pin") ?? "").split(",").filter(Boolean).map(Number),
          pout: (one(p, "pout") ?? "").split(",").filter(Boolean).map(Number),
          r: Object.fromEntries((one(p, "r") ?? "").split(",").filter(Boolean).map((x) => x.split(":").map(Number))),
        }}
      />
    </main>
  );
}
