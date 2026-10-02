"""Team need grades: where each team is short or deep, graded against the other 31 (CLAUDE.md section 6).

Usage:
    python -m pipeline.models.team_grades

Each category uses one metric. Teams are z-scored across the league (higher always means better) and
mapped to grades: z <= -1.0 Need (-2), below -0.4 Thin (-1), within 0.4 Average (0), up to 1.0 Solid (1),
1.0 or more Surplus (2). Until every team has played 20 games this season, last season's games are
included too, so the first weeks do not swing grades. Prospect depth has no data source yet and is not graded.
"""

from datetime import date
from statistics import mean, pstdev

from pipeline.db import connect
from pipeline.jobs import job_run

MIN_GAMES = 20

# category -> (metric from the per-team sums below, higher_is_better). Each is documented in CLAUDE.md.
CATEGORIES = {
    "goal_scoring": (lambda t: t["goals_for"] / t["gp"], True),            # goals for per game
    "playmaking": (lambda t: t["primary_assists"] / t["gp"], True),        # primary assists per game
    "physicality": (lambda t: (t["hits"] + t["blocks"]) / t["gp"], True),  # hits plus blocks per game
    "defense_5v5": (lambda t: t["xga_5v5"] * 3600 / t["toi_5v5"], False), # 5v5 xG against per 60
    "power_play": (lambda t: t["pp_pct"], True),                           # PP%, from the NHL
    "penalty_kill": (lambda t: t["pk_pct"], True),                         # PK%, from the NHL
    "goaltending": (lambda t: t["gsax"] / t["gp"], True),                  # GSAx per game
}


def grade(z: float) -> int:
    if z <= -1.0:
        return -2
    if z < -0.4:
        return -1
    if z < 0.4:
        return 0
    if z < 1.0:
        return 1
    return 2


def zscores(values: dict[int, float], higher_is_better: bool) -> dict[int, float]:
    avg, sd = mean(values.values()), pstdev(values.values())
    if not sd:
        return {k: 0.0 for k in values}
    sign = 1 if higher_is_better else -1
    return {k: sign * (v - avg) / sd for k, v in values.items()}


def seasons_used(conn) -> tuple[list[int], str]:
    current = conn.execute("select max(season_id) from games where game_type = 2").fetchone()[0]
    fewest = conn.execute(
        """select coalesce(min(n), 0) from (
             select t.id, count(g.id) as n from teams t
             left join games g on g.season_id = %s and g.game_type = 2 and g.stats_loaded_at is not null
               and t.id in (g.home_team_id, g.away_team_id)
             where t.active group by t.id) x""",
        (current,),
    ).fetchone()[0]
    if fewest >= MIN_GAMES:
        return [current], f"{current // 10000}-{str(current % 10000)[2:]} season"
    previous = current - 10001
    return [previous, current], (
        f"{previous // 10000}-{str(previous % 10000)[2:]} and {current // 10000}-{str(current % 10000)[2:]} "
        f"seasons (until every team has played {MIN_GAMES} games)"
    )


def team_totals(conn, seasons: list[int]) -> list[dict]:
    rows = conn.execute(
        """with g as (select id, season_id from games where game_type = 2 and season_id = any(%(s)s)),
           box as (
             select s.team_id, count(distinct s.game_id)::float8 as gp, sum(s.g)::float8 as goals_for,
                    sum(s.a1)::float8 as primary_assists, sum(s.hits)::float8 as hits, sum(s.blocks)::float8 as blocks
             from game_skater_stats s join g on g.id = s.game_id group by s.team_id),
           onice as (
             select o.team_id, sum(o.toi_5v5_sec)::float8 as toi_5v5, sum(o.xga)::float8 as xga_5v5
             from team_game_onice o join g on g.id = o.game_id group by o.team_id),
           special as (
             select team_id, sum(pp_pct * gp) / nullif(sum(gp), 0) as pp_pct, sum(pk_pct * gp) / nullif(sum(gp), 0) as pk_pct
             from team_season_stats where season_id = any(%(s)s) group by team_id),
           goalies as (
             select x.team_id, sum(x.xga * f.factor - x.goals_against)::float8 as gsax
             from goalie_game_xg x join g on g.id = x.game_id join xg_season_factor f on f.season_id = g.season_id
             group by x.team_id)
           select t.id as team_id, box.gp, box.goals_for, box.primary_assists, box.hits, box.blocks,
                  onice.toi_5v5, onice.xga_5v5, special.pp_pct::float8 as pp_pct, special.pk_pct::float8 as pk_pct,
                  coalesce(goalies.gsax, 0) as gsax
           from teams t join box on box.team_id = t.id
           left join onice on onice.team_id = t.id
           left join special on special.team_id = t.id
           left join goalies on goalies.team_id = t.id
           where t.active""",
        {"s": seasons},
    )
    cols = [c.name for c in rows.description]
    return [dict(zip(cols, r)) for r in rows.fetchall()]


def compute(totals: list[dict]) -> dict[str, dict[int, tuple[float, float, int]]]:
    """category -> team_id -> (value, z, grade)."""
    out = {}
    for category, (metric, higher) in CATEGORIES.items():
        values = {}
        for t in totals:
            try:
                value = metric(t)
            except (TypeError, ZeroDivisionError):
                value = None
            if value is not None:
                values[t["team_id"]] = float(value)
        if len(values) < 2:
            continue
        zs = zscores(values, higher)
        out[category] = {team: (values[team], zs[team], grade(zs[team])) for team in values}
    return out


def main() -> None:
    with job_run("team_grades") as counts, connect() as conn:
        run(conn, counts)


def run(conn, counts) -> None:
    """Computes today's grades; also called by the nightly job."""
    seasons, sample = seasons_used(conn)
    results = compute(team_totals(conn, seasons))
    today = date.today()
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("delete from team_grades where as_of = %s", (today,))
        cur.executemany(
            """insert into team_grades (team_id, as_of, category, value, z, grade, sample)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            [(team, today, cat, round(v, 4), round(z, 3), g, sample)
             for cat, by_team in results.items() for team, (v, z, g) in by_team.items()],
        )
        counts["team_grades"] = cur.rowcount
    counts["grade_categories"] = len(results)
    print(f"team grades ok from {sample}")


if __name__ == "__main__":
    main()
