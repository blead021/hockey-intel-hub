"""5v5 on-ice results for every skater and team in a game, from play-by-play and shift charts.

Usage:
    python -m pipeline.metrics.onice                      games loaded but not yet computed
    python -m pipeline.metrics.onice --season 20242025    every loaded game of a season not yet computed
    python -m pipeline.metrics.onice --season 20242025 --reload

Definitions (CLAUDE.md section 6), all at 5v5 with both goalies in net:
- Corsi (CF, CA): goals, shots on goal, missed shots, and blocked shots while on the ice.
- Fenwick (FF, FA): Corsi without blocked shots. Shots (SF, SA) include goals.
- An event counts for players on the ice when it happened: a shift that started before the event
  and ended at or after it. (A player changing on at that exact second was not on for it.)
- An attempt belongs to the shooter's team, looked up in the game roster.
- 5v5 ice time counts the seconds when shift charts show 5 skaters and a goalie for each team.
- Zone starts: shifts that began at a 5v5 faceoff, by zone from the player's view. The zone comes
  from the faceoff's rink coordinates and which end the home team defends.
- Expected goals (xGF, xGA) sum the active xG model's value for unblocked shots; high-danger
  chances (HDCF, HDCA) are unblocked shots with xG of 0.15 or more. The same run stores individual
  shooting (ixG) and goalie xG against at all strengths.
"""

import argparse
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import psycopg

from pipeline import archive
from pipeline.db import connect
from pipeline.ingest.nhl import field as nhl_field
from pipeline.ingest.nhl import toi_seconds
from pipeline.jobs import job_run
from pipeline.models import xg_score
from pipeline.models.xg_features import shot_rows

CORSI_EVENTS = {"goal", "shot-on-goal", "missed-shot", "blocked-shot"}
FIVE_ON_FIVE = "1551"  # away goalie, away skaters, home skaters, home goalie
BLUE_LINE_X = 25  # feet from center ice
SHIFT_TYPE = 517  # shift rows; 505 rows mark goals
WORKERS = 8
CONNECTION_ATTEMPTS = 3


@dataclass(frozen=True)
class Shift:
    player_id: int
    team_id: int
    period: int
    start: int
    end: int


@dataclass
class Line:
    toi: int = 0
    cf: int = 0
    ca: int = 0
    ff: int = 0
    fa: int = 0
    sf: int = 0
    sa: int = 0
    gf: int = 0
    ga: int = 0
    oz: int = 0
    nz: int = 0
    dz: int = 0
    xgf: float = 0.0
    xga: float = 0.0
    hdcf: int = 0
    hdca: int = 0
    pp_xgf: float = 0.0  # power play: his team has more skaters, both goalies in
    pp_xga: float = 0.0
    sh_xgf: float = 0.0  # penalty kill: his team has fewer skaters, both goalies in
    sh_xga: float = 0.0


@dataclass
class GameResult:
    players: dict[int, tuple[int, Line]] = field(default_factory=dict)  # player -> (team, line)
    teams: dict[int, Line] = field(default_factory=dict)
    shots_without_shooter: int = 0


def parse_shifts(body: dict) -> list[Shift]:
    shifts = []
    for row in nhl_field(body, "data", "shift chart"):
        if row.get("typeCode") != SHIFT_TYPE:
            continue
        start, end = toi_seconds(row.get("startTime")), toi_seconds(row.get("endTime"))
        if end > start:
            shifts.append(Shift(row["playerId"], row["teamId"], row["period"], start, end))
    return shifts


def zone_for(team_is_home: bool, x: float | None, home_defends: str | None) -> str | None:
    """O, N, or D for a faceoff, from one team's point of view."""
    if x is None or home_defends not in ("left", "right"):
        return None
    if abs(x) <= BLUE_LINE_X:
        return "N"
    side = "left" if x < 0 else "right"
    home_zone = "D" if side == home_defends else "O"
    if team_is_home:
        return home_zone
    return "O" if home_zone == "D" else "D"


def five_on_five_seconds(shifts: list[Shift], goalies: set[int], home: int, away: int) -> dict[int, list[bool]]:
    """For each period, whether each second was 5v5 with both goalies in net, from shift charts."""
    by_period: dict[int, list[Shift]] = defaultdict(list)
    for s in shifts:
        by_period[s.period].append(s)
    result = {}
    for period, period_shifts in by_period.items():
        length = max(s.end for s in period_shifts)
        counts = {key: [0] * (length + 1) for key in ((home, "s"), (home, "g"), (away, "s"), (away, "g"))}
        for s in period_shifts:
            key = (s.team_id, "g" if s.player_id in goalies else "s")
            if key in counts:
                counts[key][s.start] += 1
                counts[key][s.end] -= 1
        running = {key: 0 for key in counts}
        flags = []
        for t in range(length):
            for key in counts:
                running[key] += counts[key][t]
            flags.append(
                running[(home, "s")] == 5 and running[(away, "s")] == 5
                and running[(home, "g")] == 1 and running[(away, "g")] == 1
            )
        result[period] = flags
    return result


def compute_game(pbp: dict, shift_body: dict, xg_by_event: dict[int, float] | None = None) -> GameResult:
    home = nhl_field(pbp, "homeTeam.id", "play-by-play")
    away = nhl_field(pbp, "awayTeam.id", "play-by-play")
    roster = {p["playerId"]: p for p in nhl_field(pbp, "rosterSpots", "play-by-play")}
    team_of = {pid: p["teamId"] for pid, p in roster.items()}
    goalies = {pid for pid, p in roster.items() if p.get("positionCode") == "G"}
    shifts = parse_shifts(shift_body)
    skater_shifts = [s for s in shifts if s.player_id not in goalies]

    result = GameResult(teams={home: Line(), away: Line()})

    def line(player_id: int, team_id: int) -> Line:
        if player_id not in result.players:
            result.players[player_id] = (team_id, Line())
        return result.players[player_id][1]

    # 5v5 ice time from shift charts.
    flags = five_on_five_seconds(shifts, goalies, home, away)
    prefix = {}
    for period, f in flags.items():
        running, p = 0, [0]
        for v in f:
            running += v
            p.append(running)
        prefix[period] = p
    for period, p in prefix.items():
        total = p[-1]
        result.teams[home].toi += total
        result.teams[away].toi += total
    for s in skater_shifts:
        p = prefix.get(s.period)
        if p is None:
            continue
        end = min(s.end, len(p) - 1)
        line(s.player_id, s.team_id).toi += p[end] - p[min(s.start, end)]

    shifts_by_period: dict[int, list[Shift]] = defaultdict(list)
    for s in skater_shifts:
        shifts_by_period[s.period].append(s)

    for play in nhl_field(pbp, "plays", "play-by-play"):
        situation = play.get("situationCode") or ""
        if situation != FIVE_ON_FIVE:
            add_special_teams_xg(play, situation, xg_by_event, team_of, home, away, shifts_by_period, line)
            continue
        period_info = play.get("periodDescriptor") or {}
        if period_info.get("periodType") == "SO":
            continue
        kind = play.get("typeDescKey")
        details = play.get("details") or {}
        period, t = period_info.get("number"), toi_seconds(play.get("timeInPeriod"))

        if kind in CORSI_EVENTS:
            shooter = details.get("shootingPlayerId") or details.get("scoringPlayerId")
            for_team = team_of.get(shooter)
            if for_team not in (home, away):
                result.shots_without_shooter += 1
                continue
            against = away if for_team == home else home
            on_ice = [s for s in shifts_by_period.get(period, []) if s.start < t <= s.end]
            unblocked = kind != "blocked-shot"
            on_goal = kind in ("shot-on-goal", "goal")
            goal = kind == "goal"
            xg = (xg_by_event or {}).get(play.get("eventId")) if unblocked else None
            targets = [(result.teams[for_team], "f"), (result.teams[against], "a")]
            targets += [(line(s.player_id, s.team_id), "f" if s.team_id == for_team else "a") for s in on_ice]
            for tl, sign in targets:
                for attr, counts in (("c", True), ("f", unblocked), ("s", on_goal), ("g", goal)):
                    if counts:
                        setattr(tl, attr + sign, getattr(tl, attr + sign) + 1)
                if xg is not None:
                    setattr(tl, "xg" + sign, getattr(tl, "xg" + sign) + xg)
                    if xg >= xg_score.HIGH_DANGER:
                        setattr(tl, "hdc" + sign, getattr(tl, "hdc" + sign) + 1)

        elif kind == "faceoff":
            starting = [s for s in shifts_by_period.get(period, []) if s.start == t]
            for s in starting:
                zone = zone_for(s.team_id == home, details.get("xCoord"), play.get("homeTeamDefendingSide"))
                if zone:
                    pl = line(s.player_id, s.team_id)
                    attr = {"O": "oz", "N": "nz", "D": "dz"}[zone]
                    setattr(pl, attr, getattr(pl, attr) + 1)
    return result


@dataclass
class Shooting:
    team_id: int
    shots: int = 0
    goals: int = 0
    ixg: float = 0.0
    shots_5v5: int = 0
    goals_5v5: int = 0
    ixg_5v5: float = 0.0


@dataclass
class Style:
    team_id: int
    oz_hits: int = 0
    oz_takeaways: int = 0
    rush_onice_5v5: int = 0
    shots_slot: int = 0
    shots_mid: int = 0
    shots_perimeter: int = 0


SLOT_DISTANCE, SLOT_WIDTH, MID_DISTANCE = 25, 20, 45  # feet (CLAUDE.md section 6, Play style)


def shot_location(distance: float, y_abs: float) -> str:
    if distance <= SLOT_DISTANCE and y_abs <= SLOT_WIDTH:
        return "slot"
    return "mid" if distance <= MID_DISTANCE else "perimeter"


def style_counts(pbp: dict, shifts: list[Shift], rows, team_of: dict[int, int], home: int) -> dict[int, Style]:
    """Per-player counts for the Play style traits: offensive-zone hits and takeaways, 5v5 rush attempts
    while on the ice (the zone-entry estimate), and his own shot locations."""
    out: dict[int, Style] = {}

    def get(pid: int) -> Style | None:
        team = team_of.get(pid)
        if team is None:
            return None
        return out.setdefault(pid, Style(team))

    for play in pbp.get("plays", []):
        kind = play.get("typeDescKey")
        details = play.get("details") or {}
        if kind not in ("hit", "takeaway"):
            continue
        pid = details.get("hittingPlayerId") if kind == "hit" else details.get("playerId")
        st = get(pid) if pid else None
        x = details.get("xCoord")
        if st is None or x is None or abs(x) <= BLUE_LINE_X:
            continue
        # Offensive zone for his team: the end his team attacks (home attacks away from the side it defends).
        defends = play.get("homeTeamDefendingSide")
        if defends not in ("left", "right"):
            continue
        home_attacks_right = defends == "left"
        attacks_right = home_attacks_right if st.team_id == home else not home_attacks_right
        if (x > 0) == attacks_right:
            if kind == "hit":
                st.oz_hits += 1
            else:
                st.oz_takeaways += 1

    by_period: dict[int, list[Shift]] = defaultdict(list)
    for sh in shifts:
        by_period[sh.period].append(sh)
    for r in rows:
        if r.shooter_id:
            st = get(r.shooter_id)
            if st:
                loc = shot_location(r.features["distance"], r.features["y_abs"])
                setattr(st, f"shots_{loc}", getattr(st, f"shots_{loc}") + 1)
        if r.situation == FIVE_ON_FIVE and r.features["rush"]:
            period, t = r.features["period"], r.features["game_seconds"] - (r.features["period"] - 1) * 1200
            for sh in by_period.get(period, []):
                if sh.team_id == r.shooting_team and sh.start < t <= sh.end:
                    st = get(sh.player_id)
                    if st:
                        st.rush_onice_5v5 += 1
    return out


@dataclass
class GoalieXg:
    team_id: int
    shots_faced: int = 0
    goals_against: int = 0
    xga: float = 0.0
    hd_shots: int = 0  # high-danger (xG of 0.15 or more) shots on goal, for high-danger save %
    hd_goals: int = 0
    hd_xga: float = 0.0  # xG of all unblocked high-danger shots, like xga
    shots_5v5: int = 0
    goals_5v5: int = 0
    xga_5v5: float = 0.0


def shooting_and_goalies(rows, xg_by_event: dict[int, float]) -> tuple[dict[int, Shooting], dict[int, GoalieXg]]:
    """Individual shooting and goalie xG against, all strengths, from scored shot rows."""
    shooters: dict[int, Shooting] = {}
    goalies: dict[int, GoalieXg] = {}
    for r in rows:
        xg = xg_by_event.get(r.event_id)
        if xg is None:
            continue
        if r.shooter_id:
            sh = shooters.setdefault(r.shooter_id, Shooting(r.shooting_team))
            sh.shots += 1
            sh.goals += r.is_goal
            sh.ixg += xg
            if r.situation == FIVE_ON_FIVE:
                sh.shots_5v5 += 1
                sh.goals_5v5 += r.is_goal
                sh.ixg_5v5 += xg
        if r.goalie_id and not r.features["empty_net"]:
            g = goalies.setdefault(r.goalie_id, GoalieXg(r.defending_team))
            g.shots_faced += 1
            g.goals_against += r.is_goal
            g.xga += xg
            if xg >= xg_score.HIGH_DANGER:
                g.hd_shots += r.on_goal
                g.hd_goals += r.is_goal
                g.hd_xga += xg
            if r.situation == FIVE_ON_FIVE:
                g.shots_5v5 += 1
                g.goals_5v5 += r.is_goal
                g.xga_5v5 += xg
    return shooters, goalies


def add_special_teams_xg(play, situation, xg_by_event, team_of, home, away, shifts_by_period, line) -> None:
    """Power-play and penalty-kill on-ice xG for one unblocked shot outside 5v5 (both goalies in net)."""
    if not xg_by_event or len(situation) != 4 or situation[0] != "1" or situation[3] != "1":
        return
    if play.get("typeDescKey") not in ("goal", "shot-on-goal", "missed-shot"):
        return
    if (play.get("periodDescriptor") or {}).get("periodType") == "SO":
        return
    xg = xg_by_event.get(play.get("eventId"))
    details = play.get("details") or {}
    shooting = team_of.get(details.get("shootingPlayerId") or details.get("scoringPlayerId"))
    if xg is None or shooting not in (home, away):
        return
    away_skaters, home_skaters = int(situation[1]), int(situation[2])
    if away_skaters == home_skaters:
        return  # 4-on-4 and 3-on-3 are neither power play nor penalty kill
    period, t = (play.get("periodDescriptor") or {}).get("number"), toi_seconds(play.get("timeInPeriod"))
    for s in shifts_by_period.get(period, []):
        if not s.start < t <= s.end:
            continue
        own = home_skaters if s.team_id == home else away_skaters
        opp = away_skaters if s.team_id == home else home_skaters
        prefix = "pp" if own > opp else "sh"
        side = "xgf" if s.team_id == shooting else "xga"
        pl = line(s.player_id, s.team_id)
        setattr(pl, f"{prefix}_{side}", getattr(pl, f"{prefix}_{side}") + xg)


def store(conn, game_id: int, result: GameResult, shooters: dict | None = None, goalies: dict | None = None,
          xg_version: str | None = None, styles: dict | None = None) -> None:
    def xg(value: float) -> float | None:
        return round(value, 3) if xg_version else None

    def hd(value: int) -> int | None:
        return value if xg_version else None

    with conn.transaction():
        for table in ("player_game_onice", "team_game_onice", "player_game_shooting", "goalie_game_xg", "player_game_style"):
            conn.execute(f"delete from {table} where game_id = %s", (game_id,))
        with conn.cursor() as cur:
            cur.executemany(
                """insert into player_game_onice (player_id, game_id, team_id, toi_5v5_sec, cf, ca, ff, fa, sf, sa,
                       gf, ga, xgf, xga, hdcf, hdca, oz_starts, nz_starts, dz_starts, pp_xgf, pp_xga, sh_xgf, sh_xga)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    (pid, game_id, team, l.toi, l.cf, l.ca, l.ff, l.fa, l.sf, l.sa, l.gf, l.ga,
                     xg(l.xgf), xg(l.xga), hd(l.hdcf), hd(l.hdca), l.oz, l.nz, l.dz,
                     xg(l.pp_xgf), xg(l.pp_xga), xg(l.sh_xgf), xg(l.sh_xga))
                    for pid, (team, l) in result.players.items()
                ],
            )
            cur.executemany(
                """insert into team_game_onice (team_id, game_id, toi_5v5_sec, cf, ca, ff, fa, sf, sa, gf, ga,
                       xgf, xga, hdcf, hdca)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [(team, game_id, l.toi, l.cf, l.ca, l.ff, l.fa, l.sf, l.sa, l.gf, l.ga,
                  xg(l.xgf), xg(l.xga), hd(l.hdcf), hd(l.hdca)) for team, l in result.teams.items()],
            )
            if xg_version:
                cur.executemany(
                    """insert into player_game_shooting (player_id, game_id, team_id, shots, goals, ixg, shots_5v5,
                           goals_5v5, ixg_5v5) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    [(pid, game_id, sh.team_id, sh.shots, sh.goals, round(sh.ixg, 3), sh.shots_5v5, sh.goals_5v5,
                      round(sh.ixg_5v5, 3)) for pid, sh in (shooters or {}).items()],
                )
                cur.executemany(
                    """insert into player_game_style (player_id, game_id, team_id, oz_hits, oz_takeaways, rush_onice_5v5,
                           shots_slot, shots_mid, shots_perimeter) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    [(pid, game_id, st.team_id, st.oz_hits, st.oz_takeaways, st.rush_onice_5v5, st.shots_slot,
                      st.shots_mid, st.shots_perimeter) for pid, st in (styles or {}).items()],
                )
                cur.executemany(
                    """insert into goalie_game_xg (player_id, game_id, team_id, shots_faced, goals_against, xga,
                           hd_shots, hd_goals, hd_xga, shots_5v5, goals_5v5, xga_5v5)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    [(pid, game_id, g.team_id, g.shots_faced, g.goals_against, round(g.xga, 3), g.hd_shots,
                      g.hd_goals, round(g.hd_xga, 3), g.shots_5v5, g.goals_5v5, round(g.xga_5v5, 3))
                     for pid, g in (goalies or {}).items()],
                )
        conn.execute("update games set onice_loaded_at = now(), xg_version = %s where id = %s", (xg_version, game_id))


def load(game_id: int, season: int):
    return game_id, archive.get(f"nhl/pbp/{season}/{game_id}.json.gz"), archive.get(f"nhl/shifts/{season}/{game_id}.json.gz")


def run(conn, games: list[tuple[int, int]], counts) -> None:
    """Computes and stores the given (game_id, season) pairs, downloading from R2 in parallel.

    Without an active xG model, everything except the xG columns is still computed.
    """
    try:
        xg_version, model = xg_score.load(conn)
    except xg_score.NoActiveModel:
        xg_version, model = None, None
        counts["no_xg_model"] = 1
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for future in [pool.submit(load, gid, season) for gid, season in games]:
            try:
                game_id, pbp, shifts = future.result()
                rows = shot_rows(pbp) if model else []
                xg_by_event = xg_score.score(model, rows) if model else {}
                result = compute_game(pbp, shifts, xg_by_event)
                shooters, goalies = shooting_and_goalies(rows, xg_by_event)
                roster = {p["playerId"]: p for p in pbp.get("rosterSpots", [])}
                skater_team = {pid: p["teamId"] for pid, p in roster.items() if p.get("positionCode") != "G"}
                styles = style_counts(pbp, [s for s in parse_shifts(shifts) if s.player_id in skater_team],
                                      rows, skater_team, pbp["homeTeam"]["id"])
                if not result.players:
                    # No shift chart (the NHL is missing some): on-ice stats are impossible, but individual
                    # shooting and goalie xG do not need shifts, so keep those.
                    counts["games_without_shifts"] += 1
                    result = GameResult()
                store(conn, game_id, result, shooters, goalies, xg_version, styles)
                counts["games_computed"] += 1
                counts["shots_without_shooter"] += result.shots_without_shooter
            except (archive.ArchiveUnavailable, psycopg.OperationalError):
                raise  # setup or connection problem: stop, so the caller can reconnect and resume
            except Exception as exc:
                counts["games_failed"] += 1
                print(f"[onice] failed: {type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compute 5v5 on-ice results")
    parser.add_argument("--season", type=int)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)
    with job_run("onice" + (f"_{args.season}" if args.season else "")) as counts:
        done_before_reload = None
        for attempt in range(1, CONNECTION_ATTEMPTS + 1):
            try:
                # A fresh connection each attempt. Games already stored are skipped (unless --reload, where the
                # first attempt's start time marks what is already done), so a dropped connection resumes cleanly.
                with connect(autocommit=True) as conn:
                    if args.reload and done_before_reload is None:
                        done_before_reload = conn.execute("select now()").fetchone()[0]
                    pending = (
                        "and (onice_loaded_at is null or onice_loaded_at < %s)" if args.reload else
                        "and (onice_loaded_at is null or onice_loaded_at < stats_loaded_at "
                        "or xg_version is distinct from (select version from xg_models where active))"
                    )
                    params = ([args.season] if args.season else []) + ([done_before_reload] if args.reload else [])
                    games = conn.execute(
                        f"""select id, season_id from games where stats_loaded_at is not null
                            {"and season_id = %s" if args.season else ""} {pending}
                            order by game_date, id""",
                        params,
                    ).fetchall()
                    counts["games_pending"] = max(counts["games_pending"], len(games))
                    run(conn, games, counts)
                break
            except psycopg.OperationalError as exc:
                counts["reconnects"] += 1
                print(f"[onice] connection lost ({exc}); reconnecting, attempt {attempt + 1} of {CONNECTION_ATTEMPTS}")
                if attempt == CONNECTION_ATTEMPTS:
                    raise
                time.sleep(10 * attempt)
        if counts["games_failed"] > max(5, counts["games_pending"] * 0.02):
            raise RuntimeError(f"{counts['games_failed']} of {counts['games_pending']} games failed")
    print(f"onice ok: {dict(counts)}")


if __name__ == "__main__":
    main()
