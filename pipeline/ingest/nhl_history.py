"""25 seasons of NHL season totals for age curves (CLAUDE.md section 6), from the NHL stats API.

Usage:
    python -m pipeline.ingest.nhl_history                 2001-02 through last season
    python -m pipeline.ingest.nhl_history --from 20012002

One request per season for skater totals, skater birth dates, goalie totals, and goalie birth dates.
Season level only, so it fits the free database; game-by-game detail stays at the recent seasons.
"""

import argparse

from pipeline.db import connect
from pipeline.http import client, get_json
from pipeline.ingest.nhl import STATS, field
from pipeline.jobs import job_run

FIRST = 20012002


def rows(http, path: str, season: int) -> list[dict]:
    body = get_json(http, f"{STATS}/{path}", params={
        "limit": -1, "cayenneExp": f"seasonId={season} and gameTypeId=2"})
    return field(body, "data", path)


def load_season(conn, http, season: int, counts) -> None:
    births = {r["playerId"]: r.get("birthDate") for r in rows(http, "skater/bios", season)}
    births.update({r["playerId"]: r.get("birthDate") for r in rows(http, "goalie/bios", season)})
    out = []
    for r in rows(http, "skater/summary", season):
        gp = r.get("gamesPlayed") or 0
        toi = round((r.get("timeOnIcePerGame") or 0) * gp)
        out.append((r["playerId"], season, "D" if r.get("positionCode") == "D" else "F", r.get("skaterFullName") or "",
                    births.get(r["playerId"]), gp, toi or None, r.get("goals"), r.get("points"), r.get("shots"),
                    None, None, None))
    for r in rows(http, "goalie/summary", season):
        out.append((r["playerId"], season, "G", r.get("goalieFullName") or "", births.get(r["playerId"]),
                    r.get("gamesPlayed") or 0, r.get("timeOnIce"), None, None, None,
                    r.get("shotsAgainst"), r.get("saves"), r.get("goalsAgainst")))
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("delete from player_season_history where season_id = %s", (season,))
        cur.executemany(
            """insert into player_season_history (player_id, season_id, grp, name, birth_date, gp, toi_sec, goals,
                   points, shots, shots_against, saves, goals_against)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (player_id, season_id) do nothing""",
            out,
        )
    counts[f"rows_{season}"] = len(out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Load 25 seasons of NHL season totals")
    parser.add_argument("--from", dest="first", type=int, default=FIRST)
    args = parser.parse_args(argv)
    with job_run("nhl_history") as counts, connect() as conn, client() as http:
        last = conn.execute("select max(season_id) from games where game_type = 2").fetchone()[0] - 10001
        season = args.first
        while season <= last:
            if season != 20042005:      # no NHL season (lockout)
                load_season(conn, http, season, counts)
            season += 10001
    print(f"nhl history ok: {sum(counts.values())} player seasons")


if __name__ == "__main__":
    main()
