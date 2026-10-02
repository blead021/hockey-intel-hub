"""Fills penalties drawn and taken for games loaded before Game Score existed (reads play-by-play from R2).

Usage: python -m pipeline.metrics.penalties --season 20232024
New games get these counts from the nightly load directly.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor

from pipeline import archive
from pipeline.db import connect
from pipeline.ingest.nhl import penalty_counts
from pipeline.jobs import job_run

WORKERS = 8


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args(argv)
    with job_run(f"penalties_{args.season}") as counts, connect(autocommit=True) as conn:
        games = [r[0] for r in conn.execute(
            "select id from games where season_id = %s and stats_loaded_at is not null order by id", (args.season,))]

        def one(game_id):
            return game_id, penalty_counts(archive.get(f"nhl/pbp/{args.season}/{game_id}.json.gz"))

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for game_id, by_player in pool.map(one, games):
                with conn.transaction(), conn.cursor() as cur:
                    cur.execute("update game_skater_stats set penalties_drawn = 0, penalties_taken = 0 where game_id = %s", (game_id,))
                    cur.executemany(
                        "update game_skater_stats set penalties_drawn = %s, penalties_taken = %s where game_id = %s and player_id = %s",
                        [(c["drawn"], c["taken"], game_id, pid) for pid, c in by_player.items()],
                    )
                counts["games"] += 1
                counts["penalties"] += sum(c["taken"] for c in by_player.values())
    print(f"penalties ok: {dict(counts)}")


if __name__ == "__main__":
    main()
