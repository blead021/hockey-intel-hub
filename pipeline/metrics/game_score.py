"""Our Game Score: each player's impact on one game, in goals above an average player with the same ice time.

Usage:
    python -m pipeline.metrics.game_score                      current season
    python -m pipeline.metrics.game_score --season 20242025

Built from the same kinds of pieces as public goals-above-average game scores, all from our own data:

  EV offense    0.2 x (5v5 on-ice xGF - league 5v5 xGF rate x his 5v5 ice time)
  EV defense    0.2 x (league 5v5 xGA rate x his 5v5 ice time - 5v5 on-ice xGA)
  Power play    0.2 x (PP on-ice xGF - xGA - league PP rate x his PP ice time)
  Penalty kill  0.2 x (SH on-ice xGF - xGA - league PK rate x his PK ice time)
  Finishing     goals - individual xG (all strengths)
  Playmaking    0.5 x (primary assists - league primary-assist rate x his ice time)
  Penalties     0.19 x (penalties drawn - penalties taken)
  Faceoffs      0.01 x (faceoffs won - faceoffs lost)
  Goaltending   (goalies) xG against - goals against

- The 0.2 splits what happens on the ice equally among the five skaters.
- League rates are per season and per position group (forwards, defensemen), so an average player at
  his position scores about 0. Defensemen get fewer primary assists per minute than forwards; comparing
  them with all skaters would penalize them for their position.
- Every xG figure uses the season adjustment (xg_season_factor), so xG and goals are on one scale.
- 0.19 goals per penalty was measured from our data: power-play goals minus shorthanded goals, per
  penalty, was 0.183 to 0.195 in 2022-23 through 2025-26.
- 0.5 for primary assists and 0.01 per faceoff are starting values (0.01 is Luszczyszyn's), open to tuning.
- Games without NHL shift charts have no on-ice parts; the rest still count.
"""

import argparse
from dataclasses import asdict, dataclass

from pipeline.db import connect
from pipeline.ingest.nightly import current_season
from pipeline.jobs import job_run

ON_ICE_SHARE = 0.2
PLAYMAKING_WEIGHT = 0.5
PENALTY_GOALS = 0.19
FACEOFF_GOALS = 0.01


@dataclass
class Rates:
    """League rates for one season, per second of the matching ice time, in season-adjusted goals."""
    ev_xgf: float  # 5v5 on-ice xG for (equals xG against at league level)
    pp_net: float  # power play on-ice xGF - xGA
    sh_net: float  # penalty kill on-ice xGF - xGA (negative)
    a1: float  # primary assists per second of total ice time


@dataclass
class SkaterGame:
    toi_5v5: int
    xgf: float | None
    xga: float | None
    pp_toi: int
    pp_xgf: float | None
    pp_xga: float | None
    pk_toi: int
    sh_xgf: float | None
    sh_xga: float | None
    toi_all: int
    goals: int
    ixg: float
    a1: int
    drawn: int
    taken: int
    fow: int
    fol: int


@dataclass
class Components:
    ev_offense: float = 0.0
    ev_defense: float = 0.0
    power_play: float = 0.0
    penalty_kill: float = 0.0
    finishing: float = 0.0
    playmaking: float = 0.0
    penalties: float = 0.0
    faceoffs: float = 0.0
    goaltending: float = 0.0

    @property
    def total(self) -> float:
        return sum(asdict(self).values())


def skater_components(g: SkaterGame, r: Rates, factor: float) -> Components:
    """One skater's game. xG inputs are raw model values; factor is the season adjustment."""
    c = Components()
    if g.xgf is not None and g.xga is not None:
        c.ev_offense = ON_ICE_SHARE * (g.xgf * factor - r.ev_xgf * g.toi_5v5)
        c.ev_defense = ON_ICE_SHARE * (r.ev_xgf * g.toi_5v5 - g.xga * factor)
    if g.pp_xgf is not None and g.pp_xga is not None:
        c.power_play = ON_ICE_SHARE * ((g.pp_xgf - g.pp_xga) * factor - r.pp_net * g.pp_toi)
    if g.sh_xgf is not None and g.sh_xga is not None:
        c.penalty_kill = ON_ICE_SHARE * ((g.sh_xgf - g.sh_xga) * factor - r.sh_net * g.pk_toi)
    c.finishing = g.goals - g.ixg * factor
    c.playmaking = PLAYMAKING_WEIGHT * (g.a1 - r.a1 * g.toi_all)
    c.penalties = PENALTY_GOALS * (g.drawn - g.taken)
    c.faceoffs = FACEOFF_GOALS * (g.fow - g.fol)
    return c


GROUP_SQL = "case when s.position = 'D' then 'D' else 'F' end"


def season_rates(conn, season: int, factor: float) -> dict[str, Rates]:
    """League rates per position group ('F' or 'D') for one season."""
    onice = {
        grp: (ev, pp, sh)
        for grp, ev, pp, sh in conn.execute(
            f"""select {GROUP_SQL},
                      sum(o.xgf)::float8 / nullif(sum(o.toi_5v5_sec), 0),
                      sum(o.pp_xgf - o.pp_xga)::float8 / nullif(sum(s.pp_toi_sec) filter (where o.pp_xgf is not null), 0),
                      sum(o.sh_xgf - o.sh_xga)::float8 / nullif(sum(s.pk_toi_sec) filter (where o.sh_xgf is not null), 0)
               from player_game_onice o
               join game_skater_stats s on s.player_id = o.player_id and s.game_id = o.game_id
               join games g on g.id = o.game_id
               where g.season_id = %s and g.game_type = 2 and o.xgf is not null
               group by 1""",
            (season,),
        )
    }
    assists = dict(conn.execute(
        f"""select {GROUP_SQL}, sum(s.a1)::float8 / nullif(sum(s.toi_sec), 0) from game_skater_stats s
            join games g on g.id = s.game_id where g.season_id = %s and g.game_type = 2 group by 1""",
        (season,),
    ).fetchall())
    rates = {}
    for grp in ("F", "D"):
        ev, pp, sh = onice.get(grp, (0, 0, 0))
        rates[grp] = Rates(ev_xgf=(ev or 0) * factor, pp_net=(pp or 0) * factor, sh_net=(sh or 0) * factor,
                           a1=assists.get(grp) or 0)
    return rates


def compute_season(conn, season: int, counts) -> None:
    factor = conn.execute("select factor::float8 from xg_season_factor where season_id = %s", (season,)).fetchone()
    factor = factor[0] if factor else 1.0
    rates = season_rates(conn, season, factor)
    rows = conn.execute(
        f"""select s.player_id, s.game_id, s.team_id, {GROUP_SQL}, coalesce(o.toi_5v5_sec, 0), o.xgf::float8, o.xga::float8,
                  coalesce(s.pp_toi_sec, 0), o.pp_xgf::float8, o.pp_xga::float8,
                  coalesce(s.pk_toi_sec, 0), o.sh_xgf::float8, o.sh_xga::float8, s.toi_sec,
                  coalesce(sh.goals, 0), coalesce(sh.ixg, 0)::float8, s.a1, s.penalties_drawn, s.penalties_taken,
                  s.fow, s.fol
           from game_skater_stats s
           join games g on g.id = s.game_id
           left join player_game_onice o on o.player_id = s.player_id and o.game_id = s.game_id
           left join player_game_shooting sh on sh.player_id = s.player_id and sh.game_id = s.game_id
           where g.season_id = %s""",
        (season,),
    ).fetchall()
    out = []
    for row in rows:
        player_id, game_id, team_id, group, *values = row
        c = skater_components(SkaterGame(*values), rates[group], factor)
        out.append((player_id, game_id, team_id, False, c))

    for player_id, game_id, team_id, xga, ga in conn.execute(
        """select x.player_id, x.game_id, x.team_id, x.xga::float8, x.goals_against from goalie_game_xg x
           join games g on g.id = x.game_id where g.season_id = %s""",
        (season,),
    ):
        out.append((player_id, game_id, team_id, True, Components(goaltending=xga * factor - ga)))

    with conn.transaction():
        conn.execute(
            "delete from player_game_score where game_id in (select id from games where season_id = %s)", (season,)
        )
        with conn.cursor() as cur:
            cur.executemany(
                """insert into player_game_score (player_id, game_id, team_id, is_goalie, ev_offense, ev_defense,
                       power_play, penalty_kill, finishing, playmaking, penalties, faceoffs, goaltending, game_score)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    (pid, gid, tid, goalie, *(round(v, 3) for v in asdict(c).values()), round(c.total, 3))
                    for pid, gid, tid, goalie, c in out
                ],
            )
    counts[f"rows_{season}"] = len(out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compute our Game Score")
    parser.add_argument("--season", type=int, default=current_season())
    args = parser.parse_args(argv)
    with job_run(f"game_score_{args.season}") as counts, connect(autocommit=True) as conn:
        compute_season(conn, args.season, counts)
    print(f"game score ok: {dict(counts)}")


if __name__ == "__main__":
    main()
