"""NHL EDGE skating and shot tracking, season to date, for every skater who has played this season.

Usage: python -m pipeline.ingest.nhl_edge [--season 20262027]

Run weekly: season-level EDGE numbers change slowly, and each player costs one request.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from pipeline import archive
from pipeline.db import connect
from pipeline.http import HttpError, client
from pipeline.ingest import nhl
from pipeline.ingest.nightly import current_season
from pipeline.jobs import job_run
from pipeline.sources import require_enabled

WORKERS = 6


def fetch(http, player_id: int, season: int):
    try:
        body = nhl.edge_skater(http, player_id, season)
    except HttpError as exc:
        if exc.status == 404:
            return player_id, None  # no EDGE data yet, e.g. a player with one game
        raise
    archive.put(f"nhl/edge/{season}/{date.today().isoformat()}/{player_id}.json.gz", body)
    return player_id, body


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Load NHL EDGE season data for active skaters")
    parser.add_argument("--season", type=int, default=current_season())
    args = parser.parse_args(argv)

    with job_run("nhl_edge") as counts, connect() as conn, client() as http:
        require_enabled(conn, "nhl_edge")
        player_ids = [
            r[0]
            for r in conn.execute(
                """select distinct s.player_id from game_skater_stats s join games g on g.id = s.game_id
                   where g.season_id = %s and g.game_type = 2""",
                (args.season,),
            )
        ]
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            results = list(pool.map(lambda pid: fetch(http, pid, args.season), player_ids))
        rows = []
        for player_id, body in results:
            if body is None:
                counts["no_edge_data"] += 1
                continue
            e = nhl.parse_edge(body, player_id)
            rows.append((
                e.player_id, args.season, date.today(), e.games_played, e.top_speed_mph, e.top_speed_pctile,
                e.bursts_20plus, e.bursts_22plus, e.max_shot_speed_mph, e.max_shot_speed_pctile,
                e.distance_skated_mi, e.oz_time_pct, e.nz_time_pct, e.dz_time_pct, e.oz_time_pctile,
            ))
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany(
                """insert into edge_player_stats (player_id, season_id, as_of, games_played, top_speed_mph,
                       top_speed_pctile, bursts_20plus, bursts_22plus, max_shot_speed_mph, max_shot_speed_pctile,
                       distance_skated_mi, oz_time_pct, nz_time_pct, dz_time_pct, oz_time_pctile)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   on conflict (player_id, season_id) do update set as_of = excluded.as_of,
                     games_played = excluded.games_played, top_speed_mph = excluded.top_speed_mph,
                     top_speed_pctile = excluded.top_speed_pctile, bursts_20plus = excluded.bursts_20plus,
                     bursts_22plus = excluded.bursts_22plus, max_shot_speed_mph = excluded.max_shot_speed_mph,
                     max_shot_speed_pctile = excluded.max_shot_speed_pctile,
                     distance_skated_mi = excluded.distance_skated_mi, oz_time_pct = excluded.oz_time_pct,
                     nz_time_pct = excluded.nz_time_pct, dz_time_pct = excluded.dz_time_pct,
                     oz_time_pctile = excluded.oz_time_pctile""",
                rows,
            )
        counts["players"] = len(rows)
    print(f"nhl_edge ok: {dict(counts)}")


if __name__ == "__main__":
    main()
