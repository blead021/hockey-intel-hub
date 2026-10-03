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
    select id, query, row_number() over (partition by query order by published_at desc nulls last, id) as n
    from contract_news where status = 'backfill') r
    where n <= %s or query like 'backfill team %%' or query like 'backfill check %%' or query = 'backfill offseason'"""


TEAM_QUERIES = [
    '"{name}" (sign OR signs OR signed) ("two-way" OR "entry-level" OR "one-year" OR "two-year")',
    '"{name}" ("agree to terms" OR "agree to a" OR "re-sign" OR "re-signs") contract',
]
# Signings older than this have ended (two-way and entry-level deals run at most 3 years).
TEAM_SINCE = datetime(2023, 6, 1, tzinfo=UTC)


def search_teams(conn, http, abbrevs: list[str], counts) -> None:
    """For teams short of contracts: their signing news over the last three years, so depth players on
    two-way deals who are on no NHL list can be found. Headlines go in as 'backfill', as above."""
    for abbrev, name in conn.execute(
        "select abbrev, name from teams where active and abbrev = any(%s) order by abbrev", (abbrevs,)
    ).fetchall():
        keep: dict[str, object] = {}
        for template in TEAM_QUERIES:
            query = template.format(name=name)
            response = request(http, "GET", GOOGLE_NEWS_URL, params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
            archive.save("contract_backfill", f"team-{abbrev}", {"query": query, "xml": response.text})
            for i in parse_results(response.content, f"backfill team {abbrev}"):
                if is_candidate(i) and i.published_at and i.published_at >= TEAM_SINCE:
                    keep.setdefault(i.id, i)
            time.sleep(PAUSE_SECONDS)
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany(
                """insert into contract_news (id, title, outlet, url, published_at, query, status)
                   values (%s, %s, %s, %s, %s, %s, 'backfill') on conflict (id) do nothing""",
                [(i.id, i.title, i.outlet, i.url, i.published_at, i.query) for i in keep.values()],
            )
        counts[f"headlines_{abbrev}"] = len(keep)


def prune(conn) -> None:
    """Free cleanup before estimating: drop player-by-player headlines (the verified file covers those
    players) and team headlines that name a player who already has a contract."""
    conn.execute(
        """update contract_news set status = 'skipped', processed_at = now(),
               error = 'backfill: player now covered by the contracts file'
           where status = 'backfill' and query not like 'backfill team %%' and query not like 'backfill check %%'
             and query <> 'backfill offseason'"""
    )
    on_file = {
        normalize(n) for (n,) in conn.execute(
            """select coalesce(p.first_name || ' ' || p.last_name, c.player_name) from contracts c
               left join players p on p.id = c.player_id where c.status = 'active'"""
        )
    }
    drop = [
        news_id for news_id, title in conn.execute(
            "select id, title from contract_news where status = 'backfill' and query like 'backfill team %%'")
        if any(f" {name} " in f" {normalize(title)} " for name in on_file)
    ]
    conn.execute(
        """update contract_news set status = 'skipped', processed_at = now(),
               error = 'backfill: names a player whose contract is on file' where id = any(%s)""",
        (drop,),
    )


OFFSEASON = "after:2026-06-01"


def search_offseason(conn, http, counts) -> None:
    """Every transaction since the offseason began: the daily job's searches over months instead of days."""
    from pipeline.contracts.news import QUERIES

    found: dict[str, object] = {}
    for query in QUERIES:
        response = request(http, "GET", GOOGLE_NEWS_URL,
                           params={"q": f"{query} {OFFSEASON}", "hl": "en-US", "gl": "US", "ceid": "US:en"})
        archive.save("contract_backfill", "offseason", {"query": query, "xml": response.text})
        for i in parse_results(response.content, "backfill offseason"):
            if is_candidate(i):
                found.setdefault(i.id, i)
        time.sleep(PAUSE_SECONDS)
    _save(conn, found.values())
    counts["offseason_headlines"] = len(found)


def check_players(conn, http, counts) -> None:
    """Players whose contract may be out of date: filed under a team other than his NHL roster team, or
    with a real contract ($1M+) while on no NHL roster or prospect list. Each gets a search of news since
    the offseason began for trades, waivers, buyouts, and terminations."""
    rows = conn.execute(
        """select distinct p.id, p.first_name || ' ' || p.last_name
           from contracts c join players p on p.id = c.player_id
           where c.status = 'active' and (
             (p.current_team_id is not null and p.current_team_id <> c.team_id)
             or (p.current_team_id is null and p.rights_team_id is null and c.cap_hit >= 1000000))"""
    ).fetchall()
    for player_id, name in rows:
        query = (f'"{name}" (traded OR trade OR waivers OR claimed OR buyout OR "bought out" OR terminated OR signs) '
                 f"{OFFSEASON}")
        response = request(http, "GET", GOOGLE_NEWS_URL, params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
        archive.save("contract_backfill", f"check-{player_id}", {"query": query, "xml": response.text})
        items = [i for i in parse_results(response.content, f"backfill check {player_id}")
                 if is_candidate(i) and mentions_player(i.title, name)]
        _save(conn, items)
        counts["players_checked"] += 1
        counts["check_headlines"] += len(items)
        time.sleep(PAUSE_SECONDS)


def check_status(conn, http, counts) -> None:
    """Players off every NHL roster whose cap charge depends on why (injured counts in full, the minors
    only above the buried allowance): search roster-move news since training camps opened."""
    rows = conn.execute(
        """select distinct t.player_id, t.name from team_cap_charges t join contracts c on c.id = t.contract_id
           where t.kind = 'unknown' and t.player_id is not null and (c.cap_hit > 1225000 or t.charge > 0)"""
    ).fetchall()
    for player_id, name in rows:
        query = (f'"{name}" (assigned OR recalled OR "injured reserve" OR LTIR OR injury OR injured OR waivers '
                 f'OR "sent down" OR loaned) after:2026-08-15')
        response = request(http, "GET", GOOGLE_NEWS_URL, params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
        archive.save("contract_backfill", f"status-{player_id}", {"query": query, "xml": response.text})
        items = [i for i in parse_results(response.content, f"backfill check {player_id}")
                 if mentions_player(i.title, name)]
        _save(conn, items)
        counts["status_players"] += 1
        counts["status_headlines"] += len(items)
        time.sleep(PAUSE_SECONDS)


def _save(conn, items) -> None:
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            """insert into contract_news (id, title, outlet, url, published_at, query, status)
               values (%s, %s, %s, %s, %s, %s, 'backfill') on conflict (id) do nothing""",
            [(i.id, i.title, i.outlet, i.url, i.published_at, i.query) for i in items],
        )


def estimate(conn) -> None:
    prune(conn)
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
    print(f"{n} headlines handed to the contracts job (python -m pipeline.contracts.update --backfill --max {n}).")


def reapply_unmatched(conn, counts) -> None:
    """Re-applies backfill events skipped because the player could not be matched, from the details Claude
    already extracted (no new Claude cost), under the same backfill rules. Run after improving matching."""
    from pipeline.contracts.apply import Applier

    teams = dict(conn.execute("select abbrev, id from teams where active").fetchall())
    applier = Applier(conn, None, "reapply", teams, create_only=True)
    rows = conn.execute(
        """select e.id, e.details, e.news_ids, e.source_urls from contract_events e
           where e.outcome = 'skipped_unmatched' and exists (
             select 1 from contract_news n where n.id = any(e.news_ids) and n.query like 'backfill%%')"""
    ).fetchall()
    for event_id, details, news_ids, urls in rows:
        news = [{"id": i, "url": u} for i, u in zip(news_ids, urls or [None] * len(news_ids))]
        outcome = applier.apply(details, news)
        conn.execute("update contract_events set outcome = 'skipped_unmatched_retried' where id = %s", (event_id,))
        counts[f"reapplied_{outcome}"] += 1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Backfill contracts for players missing from the starting file")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--search", action="store_true")
    mode.add_argument("--teams", help="comma-separated team codes short of contracts, for example PHI,COL")
    mode.add_argument("--check", action="store_true", help="offseason transactions and flagged players (free)")
    mode.add_argument("--status", action="store_true", help="roster-move news for off-roster players (free)")
    mode.add_argument("--reapply", action="store_true", help="retry unmatched backfill events without Claude")
    mode.add_argument("--estimate", action="store_true")
    mode.add_argument("--release", action="store_true")
    args = parser.parse_args(argv)
    if args.search:
        with job_run("contract_backfill_search") as counts, connect(autocommit=True) as conn, client() as http:
            search(conn, http, counts)
            print(f"backfill search ok: {dict(counts)} at {datetime.now(UTC):%H:%M} UTC")
    if args.teams:
        with job_run("contract_backfill_teams") as counts, connect(autocommit=True) as conn, client() as http:
            search_teams(conn, http, [t.strip().upper() for t in args.teams.split(",")], counts)
            print(f"team search ok: {dict(counts)}")
    if args.status:
        with job_run("contract_backfill_status") as counts, connect(autocommit=True) as conn, client() as http:
            check_status(conn, http, counts)
            print(f"status search ok: {dict(counts)}")
    if args.check:
        with job_run("contract_backfill_check") as counts, connect(autocommit=True) as conn, client() as http:
            search_offseason(conn, http, counts)
            check_players(conn, http, counts)
            print(f"check search ok: {dict(counts)}")
    if args.reapply:
        with job_run("contract_backfill_reapply") as counts, connect(autocommit=True) as conn:
            reapply_unmatched(conn, counts)
            print(f"reapply ok: {dict(counts)}")
        return
    with connect(autocommit=True) as conn:
        if args.release:
            release(conn)
        estimate(conn)


if __name__ == "__main__":
    main()
