"""One-time backfill: contracts for players on NHL contracts who are missing from the starting file.

Usage:
    python -m pipeline.contracts.backfill --search     search news for each missing player (free, no Claude)
    python -m pipeline.contracts.backfill --estimate   count the headlines found and estimate the Claude cost
    python -m pipeline.contracts.backfill --release    hand the headlines to the contracts job (paid, ask Brian first)

Who is searched: players on a current NHL roster, or on a team's NHL prospect list, with no active
contract on file. Each gets one Google News search for their contract news (headlines, outlets, and
links only; contract database sites are excluded, as in news.py). Headlines are saved with status
'backfill', which the daily contracts job ignores until --release marks them pending. The job then
extracts and applies them under the usual rules: only completed signings are recorded, and details the
headlines do not state stay unknown. A prospect with no signing in the news stays without a contract,
which is correct for unsigned draft picks.
"""

import argparse
import time
from datetime import UTC, datetime

from pipeline import archive
from pipeline.contracts.news import is_candidate, parse_results
from pipeline.db import connect
from pipeline.http import client, request
from pipeline.ingest.contracts import normalize
from pipeline.jobs import job_run
from pipeline.sentiment.rss import GOOGLE_NEWS_URL

PAUSE_SECONDS = 1.5  # between searches, to stay polite with Google News
# Rough Claude cost per headline on the contracts model (40 headlines per request). A planning guess,
# not measured yet; check the Anthropic console after the first run and adjust.
DOLLARS_PER_HEADLINE = 0.003
# Only each player's newest headlines go to Claude: his current contract is almost always among them.
NEWEST_PER_PLAYER = 5


def missing_players(conn) -> list[tuple[int, str]]:
    return conn.execute(
        """select p.id, p.first_name || ' ' || p.last_name from players p
           where (p.current_team_id is not null or p.rights_team_id is not null)
             and not exists (select 1 from contracts c where c.player_id = p.id and c.status = 'active')
             and not exists (select 1 from contract_backfill_searches s where s.player_id = p.id)
           order by p.current_team_id is null, p.id"""
    ).fetchall()


def mentions_player(title: str, name: str) -> bool:
    """The headline must name the player: his surname, plus his first name or initial."""
    words = normalize(title).split()
    parts = normalize(name).split()
    return parts[-1] in words and any(w == parts[0] or w == parts[0][0] for w in words)


def search(conn, http, counts) -> None:
    for player_id, name in missing_players(conn):
        query = f'"{name}" (contract OR signs OR signed OR "entry-level" OR extension)'
        response = request(http, "GET", GOOGLE_NEWS_URL, params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
        archive.save("contract_backfill", str(player_id), {"query": query, "xml": response.text})
        items = parse_results(response.content, f"backfill {player_id}")
        keep = [i for i in items if is_candidate(i) and mentions_player(i.title, name)]
        with conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(
                    """insert into contract_news (id, title, outlet, url, published_at, query, status)
                       values (%s, %s, %s, %s, %s, %s, 'backfill') on conflict (id) do nothing""",
                    [(i.id, i.title, i.outlet, i.url, i.published_at, i.query) for i in keep],
                )
            conn.execute(
                "insert into contract_backfill_searches (player_id, headlines, kept) values (%s, %s, %s)",
                (player_id, len(items), len(keep)),
            )
        counts["players_searched"] += 1
        counts["headlines_kept"] += len(keep)
        if not keep:
            counts["players_without_news"] += 1
        time.sleep(PAUSE_SECONDS)


NEWEST = """select id from (
    select id, row_number() over (partition by query order by published_at desc nulls last, id) as n
    from contract_news where status = 'backfill') r where n <= %s"""


def estimate(conn) -> None:
    waiting = conn.execute(f"select count(*) from ({NEWEST}) x", (NEWEST_PER_PLAYER,)).fetchone()[0]
    searched, without = conn.execute(
        "select count(*), count(*) filter (where kept = 0) from contract_backfill_searches"
    ).fetchone()
    left = len(missing_players(conn))
    print(f"{searched} players searched ({without} with no contract news), {left} still to search.")
    print(f"{waiting} headlines to send ({NEWEST_PER_PLAYER} newest per player). "
          f"Estimated Claude cost: about ${waiting * DOLLARS_PER_HEADLINE:.2f}.")


def release(conn) -> None:
    n = conn.execute(
        f"update contract_news set status = 'pending' where id in ({NEWEST})", (NEWEST_PER_PLAYER,)
    ).rowcount
    conn.execute(
        """update contract_news set status = 'skipped', processed_at = now(),
               error = 'older backfill headline; the newest ones cover the current contract'
           where status = 'backfill'"""
    )
    print(f"{n} headlines handed to the contracts job (python -m pipeline.contracts.update --max {n}).")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Backfill contracts for players missing from the starting file")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--search", action="store_true")
    mode.add_argument("--estimate", action="store_true")
    mode.add_argument("--release", action="store_true")
    args = parser.parse_args(argv)
    if args.search:
        with job_run("contract_backfill_search") as counts, connect(autocommit=True) as conn, client() as http:
            search(conn, http, counts)
            print(f"backfill search ok: {dict(counts)} at {datetime.now(UTC):%H:%M} UTC")
    with connect(autocommit=True) as conn:
        if args.release:
            release(conn)
        estimate(conn)


if __name__ == "__main__":
    main()
