"""Finds a public source for every contract on file: the team announcement or news story of the signing.

Usage:
    python -m pipeline.contracts.sourcing --search     search news for each contract's signing (free)
    python -m pipeline.contracts.sourcing --verify     Claude reads the signing headlines and compares (paid)
    python -m pipeline.contracts.sourcing --report     counts, and every mismatch for Brian to look at

The point is that every figure on the site traces to a public announcement (decided 2026-10-02), not to a
cap database site. Headlines only, never full articles, never contract database sites (news.py excludes
them). Nothing here changes a contract: a mismatch is reported, not fixed.
"""

import argparse
import json
import re
import time
from collections import defaultdict
from datetime import UTC, datetime

from pipeline import archive
from pipeline.contracts.backfill import mentions_player
from pipeline.contracts.news import BLOCKED_OUTLETS, parse_results
from pipeline.db import connect
from pipeline.http import client, request
from pipeline.jobs import job_run
from pipeline.sentiment.rss import GOOGLE_NEWS_URL

PAUSE_SECONDS = 1.5
PER_CONTRACT = 4          # signing headlines kept per contract, newest first
# Signing headlines nearly always state money or length; others are skipped before paying for Claude.
SIGNING = re.compile(r"\$|million|\bm\b|year|entry-level|\belc\b|extension|re-sign|signs|signed|agree", re.IGNORECASE)
TOLERANCE = 0.01          # announced figures are often rounded ("$5.4 million"), so within 1% counts as a match


def contracts_to_search(conn) -> list[tuple]:
    return conn.execute(
        """select c.id, coalesce(p.first_name || ' ' || p.last_name, c.player_name), t.name
           from contracts c join teams t on t.id = c.team_id left join players p on p.id = c.player_id
           left join contract_sources s on s.contract_id = c.id
           where c.status = 'active' and s.contract_id is null
           order by c.cap_hit desc nulls last"""
    ).fetchall()


def search(conn, http, counts) -> None:
    for contract_id, name, team_name in contracts_to_search(conn):
        query = f'"{name}" (signs OR signed OR "agree to terms" OR extension OR "entry-level" OR contract)'
        response = request(http, "GET", GOOGLE_NEWS_URL, params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
        archive.save("contract_sources", str(contract_id), {"query": query, "xml": response.text})
        items = [
            i for i in parse_results(response.content, f"source {contract_id}")
            if mentions_player(i.title, name) and SIGNING.search(i.title)
            and not BLOCKED_OUTLETS.search(i.outlet or "") and not BLOCKED_OUTLETS.search(i.url or "")
        ]
        items.sort(key=lambda i: i.published_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        items = items[:PER_CONTRACT]
        with conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(
                    """insert into contract_news (id, title, outlet, url, published_at, query, status, processed_at, error)
                       values (%s, %s, %s, %s, %s, %s, 'skipped', now(), 'contract sourcing')
                       on conflict (id) do nothing""",
                    [(i.id, i.title, i.outlet, i.url, i.published_at, i.query) for i in items],
                )
            conn.execute(
                """insert into contract_sources (contract_id, status, found, searched_at)
                   values (%s, %s, %s, now())""",
                (contract_id, "searching" if items else "not_found",
                 None if not items else json.dumps({"news_ids": [i.id for i in items]})),
            )
        counts["contracts_searched"] += 1
        counts["with_headlines"] += bool(items)
        time.sleep(PAUSE_SECONDS)


def close(a, b) -> bool:
    return a is not None and b is not None and abs(a - b) <= max(a, b) * TOLERANCE


def season_id(text: str | None) -> int | None:
    m = re.fullmatch(r"(\d{4})-(\d{2})", (text or "").strip())
    return int(m.group(1)) * 10000 + int(m.group(1)) + 1 if m else None


def compare(on_file: dict, found: list[dict]) -> tuple[str, dict | None, str]:
    """Picks the announcement that describes this contract and says whether it agrees with the file."""
    best = None
    for t in found:
        cap = t.get("cap_hit")
        if cap is None and t.get("total_value") and t.get("years"):
            cap = round(t["total_value"] / t["years"])   # arithmetic on stated figures, as in apply.py
        end = season_id(t.get("end_season"))
        info = {"cap_hit": cap, "total_value": t.get("total_value"), "years": t.get("years"), "end_season": end,
                "evidence": t.get("evidence")}
        cap_ok = close(cap, on_file["cap_hit"])
        end_ok = end is None or on_file["end_season"] is None or end == on_file["end_season"]
        if cap_ok and end_ok:
            return "confirmed", info, "announcement matches cap hit" + (" and end season" if end else "")
        # Same contract (same end season) but a different figure is a real disagreement.
        if end is not None and end == on_file["end_season"] and cap is not None and not cap_ok:
            best = ("mismatch", info, f"announced cap hit {cap:,} vs {on_file['cap_hit']:,} on file")
    return best or ("not_found", None, "no announcement of this contract in the headlines found")


def verify(conn, counts) -> None:
    from pipeline.claude import client as claude_client
    from pipeline.contracts.extract import BATCH_SIZE, extract

    rows = conn.execute(
        """select s.contract_id, s.found, c.cap_hit::int, c.end_season,
                  coalesce(p.first_name || ' ' || p.last_name, c.player_name) as name
           from contract_sources s join contracts c on c.id = s.contract_id left join players p on p.id = c.player_id
           where s.status = 'searching'"""
    ).fetchall()
    news = {r[0]: dict(zip(("id", "title", "outlet", "url", "published_at"), r)) for r in conn.execute(
        "select id, title, outlet, url, published_at from contract_news where id = any(%s)",
        ([nid for r in rows for nid in r[1]["news_ids"]],),
    ).fetchall()}
    claude = claude_client()
    team_codes = dict(conn.execute("select abbrev, name from teams where active").fetchall())

    # Whole contracts per request (never split across two), up to BATCH_SIZE headlines.
    chunks, current = [], []
    for r in rows:
        items = [(r, news[nid]) for nid in r[1]["news_ids"] if nid in news]
        if current and len(current) + len(items) > BATCH_SIZE:
            chunks.append(current)
            current = []
        current.extend(items)
    if current:
        chunks.append(current)

    for chunk in chunks:
        result = extract(claude, [item for _, item in chunk], team_codes)
        counts["input_tokens"] += result.input_tokens
        counts["output_tokens"] += result.output_tokens
        per_contract: dict[int, list[dict]] = defaultdict(list)
        urls: dict[int, list[str]] = defaultdict(list)
        for t in result.transactions:
            if t["status"] != "completed" or t["type"] not in ("signing", "extension", "entry_level"):
                continue
            for i in t["items"]:
                row, item = chunk[i - 1]
                # The transaction must be about this contract's player (full name, or surname as headlines do).
                if mentions_player(t["player_name"], row[4]) or t["player_name"].split()[-1].lower() == row[4].split()[-1].lower():
                    per_contract[row[0]].append(t)
                    if item.get("url"):
                        urls[row[0]].append(item["url"])
        for row in {row[0]: row for row, _ in chunk}.values():
            contract_id = row[0]
            status, found, note = compare({"cap_hit": row[2], "end_season": row[3]}, per_contract.get(contract_id, []))
            conn.execute(
                """update contract_sources set status = %s, found = %s, note = %s, source_urls = %s, checked_at = now()
                   where contract_id = %s""",
                (status, None if found is None else json.dumps(found), note,
                 sorted(set(urls.get(contract_id, []))) or None, contract_id),
            )
            counts[f"contracts_{status}"] += 1
        counts["requests"] += 1


def report(conn) -> None:
    print(conn.execute(
        "select status, count(*) from contract_sources group by 1 order by 2 desc").fetchall())
    total = conn.execute("select count(*) from contracts where status = 'active'").fetchone()[0]
    confirmed = conn.execute("select count(*) from contract_sources where status = 'confirmed'").fetchone()[0]
    print(f"{confirmed} of {total} active contracts confirmed by a public announcement.")
    for row in conn.execute(
        """select t.abbrev, coalesce(p.first_name || ' ' || p.last_name, c.player_name), c.cap_hit::int, s.note,
                  s.source_urls[1]
           from contract_sources s join contracts c on c.id = s.contract_id join teams t on t.id = c.team_id
           left join players p on p.id = c.player_id where s.status = 'mismatch' order by 1, 2"""
    ).fetchall():
        print("  mismatch:", row)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Find a public source for every contract on file")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--search", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)
    if args.search:
        with job_run("contract_sourcing_search") as counts, connect(autocommit=True) as conn, client() as http:
            search(conn, http, counts)
            print(f"sourcing search ok: {dict(counts)}")
    elif args.verify:
        with job_run("contract_sourcing_verify") as counts, connect(autocommit=True) as conn:
            verify(conn, counts)
            print(f"sourcing verify ok: {dict(counts)}")
    else:
        with connect() as conn:
            report(conn)


if __name__ == "__main__":
    main()
