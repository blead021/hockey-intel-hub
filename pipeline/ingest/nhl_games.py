"""Games: season schedules, then boxscore, play-by-play, and shifts for each finished game.

Boxscore, play-by-play, and shift files go to R2 at fixed keys (nhl/{kind}/{season}/{game_id}.json.gz),
where later jobs read them. Per-game skater and goalie lines go to Postgres.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta

from pipeline import archive
from pipeline.ingest import nhl
from pipeline.ingest.nhl import GameRow
from pipeline.ingest.nhl_players import upsert_players
from pipeline.ingest.nhl_teams import ensure_teams

FETCH_WORKERS = 6
TOI_CHUNK_DAYS = 31


def sync_schedule(conn, http, season: int) -> int:
    """Upserts every regular season and playoff game of a season, from all teams' schedules."""
    teams = [r[0] for r in conn.execute("select abbrev from teams where active order by abbrev")]
    games: dict[int, GameRow] = {}
    for abbrev in teams:
        for g in nhl.parse_club_schedule(nhl.club_season_schedule(http, abbrev, season)):
            games[g.id] = g
    with conn.transaction():
        conn.execute("insert into seasons (id) values (%s) on conflict do nothing", (season,))
        ensure_teams(conn, http, {g.home_team_id for g in games.values()} | {g.away_team_id for g in games.values()})
        with conn.cursor() as cur:
            cur.executemany(
                """insert into games (id, season_id, game_type, game_date, start_time_utc, home_team_id,
                       away_team_id, home_score, away_score, state, venue, last_period_type, updated_at)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                   on conflict (id) do update set game_date = excluded.game_date,
                     start_time_utc = excluded.start_time_utc, home_score = excluded.home_score,
                     away_score = excluded.away_score, state = excluded.state, venue = excluded.venue,
                     last_period_type = excluded.last_period_type, updated_at = now()""",
                [
                    (g.id, g.season_id, g.game_type, g.game_date, g.start_time_utc, g.home_team_id,
                     g.away_team_id, g.home_score, g.away_score, g.state, g.venue, g.last_period_type)
                    for g in games.values()
                ],
            )
    return len(games)


@dataclass
class FetchedGame:
    game_id: int
    season_id: int
    box: dict
    pbp: dict
    shifts: dict


def fetch_game(http, game_id: int, season_id: int) -> FetchedGame:
    """Downloads and archives one game. Safe to run in several threads at once."""
    fetched = FetchedGame(
        game_id, season_id, nhl.boxscore(http, game_id), nhl.play_by_play(http, game_id), nhl.shift_chart(http, game_id)
    )
    archive.put(f"nhl/boxscore/{season_id}/{game_id}.json.gz", fetched.box)
    archive.put(f"nhl/pbp/{season_id}/{game_id}.json.gz", fetched.pbp)
    archive.put(f"nhl/shifts/{season_id}/{game_id}.json.gz", fetched.shifts)
    return fetched


def goalie_goals(pbp: dict, goalie_ids: set[int]) -> dict[int, int]:
    """Goals scored by goalies (rare, but real), per team. Goalie lines have no goals column."""
    goals: dict[int, int] = {}
    for play in pbp.get("plays", []):
        details = play.get("details") or {}
        if (
            play.get("typeDescKey") == "goal"
            and (play.get("periodDescriptor") or {}).get("periodType") != "SO"
            and details.get("scoringPlayerId") in goalie_ids
        ):
            team = details.get("eventOwnerTeamId")
            goals[team] = goals.get(team, 0) + 1
    return goals


def check_game(box: dict, skaters: list[nhl.SkaterLine], goalie_goal_counts: dict[int, int] | None = None) -> list[str]:
    """Cross-checks that should always hold. Problems are reported, not hidden."""
    goalie_goal_counts = goalie_goal_counts or {}
    problems = []
    for s in skaters:
        if s.a1 + s.a2 != s.assists:
            problems.append(f"player {s.player_id}: boxscore has {s.assists} assists, play-by-play {s.a1 + s.a2}")
    shootout = (box.get("gameOutcome") or {}).get("lastPeriodType") == "SO"
    for side in ("awayTeam", "homeTeam"):
        team_id = box[side]["id"]
        goals = sum(s.g for s in skaters if s.team_id == team_id)
        score = box[side].get("score", 0)
        other = box["homeTeam" if side == "awayTeam" else "awayTeam"].get("score", 0)
        expected = score - 1 if shootout and score > other else score  # the shootout winner gets +1
        expected -= goalie_goal_counts.get(team_id, 0)
        if goals != expected:
            problems.append(f"team {team_id}: skater goals {goals}, expected {expected}")
    return problems


def store_game(conn, fetched: FetchedGame, counts) -> None:
    state = nhl.field(fetched.box, "gameState", "boxscore")
    if state not in nhl.FINAL_STATES:
        counts["games_not_final"] += 1
        return
    skaters, goalies = nhl.parse_boxscore(fetched.box)
    credits = nhl.pbp_credits(fetched.pbp)
    penalties = nhl.penalty_counts(fetched.pbp)
    for s in skaters:
        c = credits.get(s.player_id, {})
        s.a1, s.a2, s.fow, s.fol = c.get("a1", 0), c.get("a2", 0), c.get("fow", 0), c.get("fol", 0)

    goalie_ids = {p.id for p in nhl.pbp_players(fetched.pbp) if p.position == "G"}
    for problem in check_game(fetched.box, skaters, goalie_goals(fetched.pbp, goalie_ids)):
        counts["check_problems"] += 1
        print(f"[game {fetched.game_id}] {problem}")
    if not fetched.shifts.get("data"):
        counts["games_without_shifts"] += 1

    with conn.transaction():
        upsert_players(conn, nhl.pbp_players(fetched.pbp))
        conn.execute("delete from game_skater_stats where game_id = %s", (fetched.game_id,))
        conn.execute("delete from game_goalie_stats where game_id = %s", (fetched.game_id,))
        with conn.cursor() as cur:
            cur.executemany(
                """insert into game_skater_stats (player_id, game_id, team_id, position, g, a1, a2, sog, hits,
                       blocks, pim, plus_minus, giveaways, takeaways, shifts, toi_sec, fow, fol,
                       penalties_drawn, penalties_taken)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    (s.player_id, fetched.game_id, s.team_id, s.position, s.g, s.a1, s.a2, s.sog, s.hits,
                     s.blocks, s.pim, s.plus_minus, s.giveaways, s.takeaways, s.shifts, s.toi_sec, s.fow, s.fol,
                     penalties.get(s.player_id, {}).get("drawn", 0), penalties.get(s.player_id, {}).get("taken", 0))
                    for s in skaters
                ],
            )
            cur.executemany(
                """insert into game_goalie_stats (player_id, game_id, team_id, started, decision, shots_against,
                       saves, ga, ev_shots_against, ev_ga, pp_shots_against, pp_ga, sh_shots_against, sh_ga, toi_sec)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    (g.player_id, fetched.game_id, g.team_id, g.started, g.decision, g.shots_against, g.saves,
                     g.ga, g.ev_shots_against, g.ev_ga, g.pp_shots_against, g.pp_ga, g.sh_shots_against,
                     g.sh_ga, g.toi_sec)
                    for g in goalies
                ],
            )
        conn.execute(
            """update games set state = %s, home_score = %s, away_score = %s, last_period_type = %s,
                 stats_loaded_at = now(), updated_at = now() where id = %s""",
            (
                state,
                fetched.box["homeTeam"].get("score"),
                fetched.box["awayTeam"].get("score"),
                (fetched.box.get("gameOutcome") or {}).get("lastPeriodType"),
                fetched.game_id,
            ),
        )
    counts["games_loaded"] += 1
    counts["skater_lines"] += len(skaters)
    counts["goalie_lines"] += len(goalies)


def load_games(conn, http, games: list[tuple[int, int]], counts) -> list[int]:
    """Fetches games in parallel and stores them one at a time. Returns the ids that failed."""
    failed = []
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        futures = {pool.submit(fetch_game, http, gid, season): gid for gid, season in games}
        for future, game_id in futures.items():
            try:
                store_game(conn, future.result(), counts)
            except archive.ArchiveUnavailable:
                raise
            except Exception as exc:  # one bad game must not stop the rest
                failed.append(game_id)
                counts["games_failed"] += 1
                print(f"[game {game_id}] failed: {type(exc).__name__}: {exc}")
    return failed


def load_time_on_ice(conn, http, start: date, end: date, counts) -> None:
    """Adds even strength, power play, and shorthanded ice time from the NHL stats API."""
    day = start
    while day <= end:
        chunk_end = min(day + timedelta(days=TOI_CHUNK_DAYS - 1), end)
        rows = nhl.time_on_ice_report(http, day, chunk_end)
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany(
                """update game_skater_stats set ev_toi_sec = %s, pp_toi_sec = %s, pk_toi_sec = %s
                   where player_id = %s and game_id = %s""",
                [
                    (r.get("evTimeOnIce"), r.get("ppTimeOnIce"), r.get("shTimeOnIce"), r["playerId"], r["gameId"])
                    for r in rows
                ],
            )
            counts["toi_rows_updated"] += cur.rowcount
        counts["toi_rows_reported"] += len(rows)
        day = chunk_end + timedelta(days=1)
