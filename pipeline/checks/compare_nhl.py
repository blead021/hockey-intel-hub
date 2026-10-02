"""Compares our season totals with the NHL's official ones, player by player.

Usage: python -m pipeline.checks.compare_nhl --season 20232024

Reads the NHL stats API's season summaries (the numbers NHL.com shows) and our game-by-game tables,
and lists every player whose totals differ. Run it after a season finishes loading.
"""

import argparse
from collections import Counter

from pipeline.db import connect
from pipeline.http import client, get_json
from pipeline.ingest.nhl import STATS

SKATER_FIELDS = {  # NHL summary field -> our column
    "gamesPlayed": "gp", "goals": "g", "assists": "a", "points": "pts", "plusMinus": "plus_minus",
    "shots": "sog", "penaltyMinutes": "pim",
}
GOALIE_FIELDS = {
    "gamesPlayed": "gp", "gamesStarted": "gs", "wins": "w", "losses": "l", "otLosses": "otl",
    "shotsAgainst": "shots_against", "saves": "saves", "goalsAgainst": "ga",
}


def nhl_summary(http, kind: str, season: int) -> dict[int, dict]:
    body = get_json(
        http,
        f"{STATS}/{kind}/summary",
        params={"isAggregate": "true", "isGame": "false", "start": 0, "limit": -1,
                "cayenneExp": f"seasonId={season} and gameTypeId=2"},
    )
    return {row["playerId"]: row for row in body["data"]}


def compare(ours: dict[int, dict], theirs: dict[int, dict], fields: dict[str, str]) -> tuple[list[str], Counter]:
    problems, counts = [], Counter()
    for player_id in sorted(set(ours) | set(theirs)):
        mine, nhl = ours.get(player_id), theirs.get(player_id)
        if mine is None:
            problems.append(f"{player_id} {nhl.get('skaterFullName') or nhl.get('goalieFullName')}: missing from our data")
            counts["missing_ours"] += 1
            continue
        if nhl is None:
            problems.append(f"{player_id}: in our data but not in the NHL summary")
            counts["missing_nhl"] += 1
            continue
        diffs = [f"{f} NHL {nhl.get(f)} vs ours {mine[c]}" for f, c in fields.items() if (nhl.get(f) or 0) != mine[c]]
        if diffs:
            name = nhl.get("skaterFullName") or nhl.get("goalieFullName")
            problems.append(f"{player_id} {name}: " + "; ".join(diffs))
            counts["players_differing"] += 1
        else:
            counts["players_matching"] += 1
    return problems, counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args(argv)

    with connect() as conn, client() as http:
        loaded, total = conn.execute(
            """select count(*) filter (where stats_loaded_at is not null), count(*) from games
               where season_id = %s and game_type = 2 and state in ('OFF', 'FINAL')""",
            (args.season,),
        ).fetchone()
        print(f"{args.season}: {loaded} of {total} finished regular season games loaded")

        skaters = {
            r[0]: dict(zip(SKATER_FIELDS.values(), r[1:]))
            for r in conn.execute(
                """select player_id, sum(gp)::int, sum(g)::int, sum(a)::int, sum(pts)::int, sum(plus_minus)::int,
                          sum(sog)::int, sum(pim)::int
                   from skater_season_stats where season_id = %s and game_type = 2 group by player_id""",
                (args.season,),
            )
        }
        goalies = {
            r[0]: dict(zip(GOALIE_FIELDS.values(), r[1:]))
            for r in conn.execute(
                """select player_id, sum(gp)::int, sum(gs)::int, sum(w)::int, sum(l)::int, sum(otl)::int,
                          sum(shots_against)::int, sum(saves)::int, sum(ga)::int
                   from goalie_season_stats where season_id = %s and game_type = 2 group by player_id""",
                (args.season,),
            )
        }
        failures = 0
        for label, ours, kind, fields in (("Skaters", skaters, "skater", SKATER_FIELDS),
                                          ("Goalies", goalies, "goalie", GOALIE_FIELDS)):
            problems, counts = compare(ours, nhl_summary(http, kind, args.season), fields)
            print(f"\n{label}: {dict(counts)}")
            for p in problems[:40]:
                print(f"  {p}")
            if len(problems) > 40:
                print(f"  ... and {len(problems) - 40} more")
            failures += len(problems)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
