"""PuckSleuth WAR (an estimate): wins above a replacement-level player, from our Game Score.

Usage:
    python -m pipeline.models.war              every loaded season
    python -m pipeline.models.war --season 20262027

Game Score already measures each game's impact in goals above an AVERAGE player with the same ice time
(even strength offense and defense, power play, penalty kill, finishing, playmaking, penalties, faceoffs;
goalies: goals saved above expected). WAR re-bases that on a REPLACEMENT-level player, the kind of depth
player any team can call up, and converts goals to wins:

1. Replacement level, per position group and season: the Game Score rate of players outside the league's
   regular lineup spots by ice time (forwards below 13 per team, defensemen below 7, goalies below 2).
   Skaters per 60 minutes, goalies per game.
2. GAR (goals above replacement) = season Game Score total - replacement rate x his ice time (or games).
3. WAR = GAR / goals per win, where goals per win comes from our team results: the slope of wins on goal
   differential across all full seasons on file (about 6.2 goals per win).

Labeled on the site as "PuckSleuth WAR (estimate)" (CLAUDE.md section 6).
"""

import argparse

from pipeline.db import connect
from pipeline.jobs import job_run

REGULARS_PER_TEAM = {"F": 13, "D": 7, "G": 2}
MIN_REPLACEMENT_TOI = 60 * 60     # skaters need an hour of ice time to count toward replacement level
MIN_REPLACEMENT_HOURS = 300       # below this much fringe ice time (early season), use last season's level
DEFAULT_GOALS_PER_WIN = 6.0       # used only if no full season is on file


def goals_per_win(conn) -> float:
    slope = conn.execute(
        """select regr_slope(w::float8, (goals_for - goals_against)::float8)
           from team_season_stats where gp >= 60"""
    ).fetchone()[0]
    return 1 / slope if slope and slope > 0 else DEFAULT_GOALS_PER_WIN


def season_totals(conn, season: int) -> list[dict]:
    rows = conn.execute(
        """with gs as (
             select gs.player_id, sum(gs.game_score)::float8 as gaa, count(*)::int as gp, bool_or(gs.is_goalie) as goalie
             from player_game_score gs join games g on g.id = gs.game_id
             where g.season_id = %(s)s and g.game_type = 2 group by gs.player_id),
           toi as (
             select player_id, sum(toi_sec)::float8 as toi from game_skater_stats s join games g on g.id = s.game_id
             where g.season_id = %(s)s and g.game_type = 2 group by player_id
             union all
             select player_id, sum(toi_sec)::float8 from game_goalie_stats s join games g on g.id = s.game_id
             where g.season_id = %(s)s and g.game_type = 2 group by player_id)
           select gs.player_id, gs.gaa, gs.gp, coalesce(t.toi, 0) as toi,
                  case when gs.goalie then 'G' when p.position = 'D' then 'D' else 'F' end as grp
           from gs join players p on p.id = gs.player_id left join toi t on t.player_id = gs.player_id""",
        {"s": season},
    )
    cols = [c.name for c in rows.description]
    return [dict(zip(cols, r)) for r in rows.fetchall()]


def replacement_rates(players: list[dict], teams: int, fallback: dict[str, float] | None = None) -> dict[str, float]:
    """Game Score per 60 (skaters) or per game (goalies) of players outside the regular lineup spots. Early in a
    season there is too little fringe play to measure, so the fallback (last season's level) is used."""
    rates = {}
    for grp, per_team in REGULARS_PER_TEAM.items():
        group = sorted((p for p in players if p["grp"] == grp), key=lambda p: p["toi"], reverse=True)
        fringe = group[per_team * teams:]
        if grp == "G":
            games = sum(p["gp"] for p in fringe)
            enough = games >= MIN_REPLACEMENT_HOURS / 10
            rates[grp] = sum(p["gaa"] for p in fringe) / games if games and enough else None
        else:
            fringe = [p for p in fringe if p["toi"] >= MIN_REPLACEMENT_TOI]
            hours = sum(p["toi"] for p in fringe) / 3600
            rates[grp] = sum(p["gaa"] for p in fringe) / hours if hours >= MIN_REPLACEMENT_HOURS else None
    for grp, rate in rates.items():
        if rate is None:
            rates[grp] = (fallback or {}).get(grp, 0.0)
    return rates


def war_rows(players: list[dict], rates: dict[str, float], gpw: float) -> list[tuple]:
    out = []
    for p in players:
        exposure = p["gp"] if p["grp"] == "G" else p["toi"] / 3600
        gar = p["gaa"] - rates[p["grp"]] * exposure
        out.append((p["player_id"], p["grp"], p["gp"], int(p["toi"]), round(p["gaa"], 3), round(gar, 3), round(gar / gpw, 3)))
    return out


def compute(conn, season: int, counts) -> None:
    players = season_totals(conn, season)
    if not players:
        return
    teams = conn.execute("select count(*) from teams where active").fetchone()[0]
    last = conn.execute(
        """select replacement_f, replacement_d, replacement_g from war_constants where season_id < %s
           order by season_id desc limit 1""", (season,)).fetchone()
    fallback = {"F": float(last[0]), "D": float(last[1]), "G": float(last[2])} if last else None
    rates = replacement_rates(players, teams, fallback)
    gpw = goals_per_win(conn)
    rows = war_rows(players, rates, gpw)
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("delete from player_war where season_id = %s", (season,))
        cur.executemany(
            """insert into player_war (player_id, season_id, grp, gp, toi_sec, gaa, gar, war)
               values (%s, %s, %s, %s, %s, %s, %s, %s)""",
            [(pid, season, grp, gp, toi, gaa, gar, war) for pid, grp, gp, toi, gaa, gar, war in rows],
        )
        cur.execute(
            """insert into war_constants (season_id, goals_per_win, replacement_f, replacement_d, replacement_g)
               values (%s, %s, %s, %s, %s)
               on conflict (season_id) do update set goals_per_win = excluded.goals_per_win,
                 replacement_f = excluded.replacement_f, replacement_d = excluded.replacement_d,
                 replacement_g = excluded.replacement_g, computed_at = now()""",
            (season, gpw, rates["F"], rates["D"], rates["G"]),
        )
    counts[f"war_players_{season}"] = len(rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compute PuckSleuth WAR (estimate)")
    parser.add_argument("--season", type=int)
    args = parser.parse_args(argv)
    with job_run("war") as counts, connect() as conn:
        seasons = [args.season] if args.season else [
            s for (s,) in conn.execute("select distinct season_id from games where game_type = 2 order by 1")]
        for season in seasons:
            compute(conn, season, counts)
    print(f"war ok: {dict(counts)}")


if __name__ == "__main__":
    main()
