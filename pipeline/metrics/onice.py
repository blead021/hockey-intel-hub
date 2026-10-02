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
"""

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from pipeline import archive
from pipeline.db import connect
from pipeline.ingest.nhl import field as nhl_field
from pipeline.ingest.nhl import toi_seconds
from pipeline.jobs import job_run

CORSI_EVENTS = {"goal", "shot-on-goal", "missed-shot", "blocked-shot"}
FIVE_ON_FIVE = "1551"  # away goalie, away skaters, home skaters, home goalie
BLUE_LINE_X = 25  # feet from center ice
SHIFT_TYPE = 517  # shift rows; 505 rows mark goals
WORKERS = 8


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


def compute_game(pbp: dict, shift_body: dict) -> GameResult:
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
        if play.get("situationCode") != FIVE_ON_FIVE:
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
            for team, sign in ((for_team, "f"), (against, "a")):
                tl = result.teams[team]
                for attr, counts in (("c", True), ("f", unblocked), ("s", on_goal), ("g", goal)):
                    if counts:
                        setattr(tl, attr + sign, getattr(tl, attr + sign) + 1)
            for s in on_ice:
                pl = line(s.player_id, s.team_id)
                sign = "f" if s.team_id == for_team else "a"
                for attr, counts in (("c", True), ("f", unblocked), ("s", on_goal), ("g", goal)):
                    if counts:
                        setattr(pl, attr + sign, getattr(pl, attr + sign) + 1)

        elif kind == "faceoff":
            starting = [s for s in shifts_by_period.get(period, []) if s.start == t]
            for s in starting:
                zone = zone_for(s.team_id == home, details.get("xCoord"), play.get("homeTeamDefendingSide"))
                if zone:
                    pl = line(s.player_id, s.team_id)
                    attr = {"O": "oz", "N": "nz", "D": "dz"}[zone]
                    setattr(pl, attr, getattr(pl, attr) + 1)
    return result


def store(conn, game_id: int, result: GameResult) -> None:
    with conn.transaction():
        conn.execute("delete from player_game_onice where game_id = %s", (game_id,))
        conn.execute("delete from team_game_onice where game_id = %s", (game_id,))
        with conn.cursor() as cur:
            cur.executemany(
                """insert into player_game_onice (player_id, game_id, team_id, toi_5v5_sec, cf, ca, ff, fa, sf, sa,
                       gf, ga, oz_starts, nz_starts, dz_starts)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    (pid, game_id, team, l.toi, l.cf, l.ca, l.ff, l.fa, l.sf, l.sa, l.gf, l.ga, l.oz, l.nz, l.dz)
                    for pid, (team, l) in result.players.items()
                ],
            )
            cur.executemany(
                """insert into team_game_onice (team_id, game_id, toi_5v5_sec, cf, ca, ff, fa, sf, sa, gf, ga)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [(team, game_id, l.toi, l.cf, l.ca, l.ff, l.fa, l.sf, l.sa, l.gf, l.ga) for team, l in result.teams.items()],
            )
        conn.execute("update games set onice_loaded_at = now() where id = %s", (game_id,))


def load(game_id: int, season: int):
    return game_id, archive.get(f"nhl/pbp/{season}/{game_id}.json.gz"), archive.get(f"nhl/shifts/{season}/{game_id}.json.gz")


def run(conn, games: list[tuple[int, int]], counts) -> None:
    """Computes and stores the given (game_id, season) pairs, downloading from R2 in parallel."""
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for future in [pool.submit(load, gid, season) for gid, season in games]:
            try:
                game_id, pbp, shifts = future.result()
                result = compute_game(pbp, shifts)
                if not result.players:
                    counts["games_without_shifts"] += 1
                    continue
                store(conn, game_id, result)
                counts["games_computed"] += 1
                counts["shots_without_shooter"] += result.shots_without_shooter
            except archive.ArchiveUnavailable:
                raise
            except Exception as exc:
                counts["games_failed"] += 1
                print(f"[onice] failed: {type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compute 5v5 on-ice results")
    parser.add_argument("--season", type=int)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)
    with job_run("onice" + (f"_{args.season}" if args.season else "")) as counts, connect(autocommit=True) as conn:
        games = conn.execute(
            f"""select id, season_id from games where stats_loaded_at is not null
                {"and season_id = %s" if args.season else ""}
                {"" if args.reload else "and (onice_loaded_at is null or onice_loaded_at < stats_loaded_at)"}
                order by game_date, id""",
            (args.season,) if args.season else (),
        ).fetchall()
        counts["games_pending"] = len(games)
        run(conn, games, counts)
        if counts["games_failed"] > max(5, len(games) * 0.02):
            raise RuntimeError(f"{counts['games_failed']} of {len(games)} games failed")
    print(f"onice ok: {dict(counts)}")


if __name__ == "__main__":
    main()
