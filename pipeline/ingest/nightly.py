"""Nightly NHL load, and the backfill command for whole seasons.

Usage:
    python -m pipeline.ingest.nightly                      new finished games this season (and the last
                                                           3 days again, for NHL corrections), plus rosters
    python -m pipeline.ingest.nightly --season 20232024    every finished game of that season not yet loaded
    python -m pipeline.ingest.nightly --reload             reload games already loaded (with --season)

Safe to rerun: games are replaced, never duplicated. The job fails if more than 5% of games fail.
"""

import argparse
from collections import Counter
from datetime import date

from pipeline.db import connect
from pipeline.http import client
from pipeline.jobs import job_run
from pipeline.sources import require_enabled

MAX_FAILURE_RATE = 0.05
RELOAD_RECENT_DAYS = 3


def current_season(today: date | None = None) -> int:
    """NHL seasons start in the fall: September 2026 onward is 20262027."""
    today = today or date.today()
    start = today.year if today.month >= 9 else today.year - 1
    return start * 10000 + start + 1


class TooManyFailures(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> None:
    from pipeline.ingest import nhl_games, nhl_players, nhl_teams
    from pipeline.metrics import game_score, onice

    parser = argparse.ArgumentParser(description="Load NHL games, stats, and rosters")
    parser.add_argument("--season", type=int, help="backfill one season (e.g. 20232024)")
    parser.add_argument("--reload", action="store_true", help="also reload games already loaded")
    args = parser.parse_args(argv)
    season = args.season or current_season()
    backfill = args.season is not None

    with job_run(f"nhl_{'backfill_' + str(season) if backfill else 'nightly'}") as counts, \
            connect(autocommit=True) as conn, client() as http:
        require_enabled(conn, "nhl_api")
        nhl_teams.refresh(conn, http, counts)
        counts["schedule_games"] = nhl_games.sync_schedule(conn, http, season)
        nhl_teams.refresh_season_stats(conn, http, season, counts)

        # Finished games only, up to yesterday (today's games may still be in progress). The NHL corrects
        # boxscores for a few days after a game (starting goalies, assists), so recent games are reloaded too.
        pending = conn.execute(
            f"""select id, season_id, game_date from games
                where season_id = %s and game_date < current_date and state in ('OFF', 'FINAL')
                {"" if args.reload else "and (stats_loaded_at is null or game_date >= current_date - %s)"}
                order by game_date, id""",
            (season,) if args.reload else (season, RELOAD_RECENT_DAYS),
        ).fetchall()
        counts["games_pending"] = len(pending)
        failed = nhl_games.load_games(conn, http, [(gid, sid) for gid, sid, _ in pending], counts)

        # The stats API publishes ice-time splits a while after each game, so fill any game still missing them.
        first, last = conn.execute(
            """select min(g.game_date), max(g.game_date) from games g
               where g.season_id = %s and exists (
                 select 1 from game_skater_stats s where s.game_id = g.id and s.pp_toi_sec is null)""",
            (season,),
        ).fetchone()
        if first:
            nhl_games.load_time_on_ice(conn, http, first, last, counts)

        # 5v5 on-ice results from the play-by-play and shift files just stored in R2.
        onice_games = conn.execute(
            """select id, season_id from games where season_id = %s and stats_loaded_at is not null
               and (onice_loaded_at is null or onice_loaded_at < stats_loaded_at) order by game_date, id""",
            (season,),
        ).fetchall()
        onice_counts = Counter()
        onice.run(conn, onice_games, onice_counts)
        counts.update({f"onice_{k}": v for k, v in onice_counts.items()})
        game_score.compute_season(conn, season, counts)  # league rates change daily, so redo the season

        if not backfill:
            nhl_players.refresh_rosters(conn, http, counts)
        nhl_players.fill_missing_bios(conn, http, counts)

        if pending and len(failed) / len(pending) > MAX_FAILURE_RATE:
            raise TooManyFailures(f"{len(failed)} of {len(pending)} games failed: {failed[:20]}")
    print(f"nightly ok: {dict(counts)}")


if __name__ == "__main__":
    main()
