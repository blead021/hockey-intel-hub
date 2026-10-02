"""Daily job that keeps contracts current from team announcements and news coverage.

Usage:
    python -m pipeline.contracts.update             collect news, extract with Claude, apply, log
    python -m pipeline.contracts.update --dry-run   extract and print; no contract changes

Headlines whose Claude request failed are retried on the next run.

Steps: find transaction headlines (news.py), have Claude turn them into structured transactions
(extract.py), apply them under fixed rules (apply.py), and log each change with its sources in
contract_changes. To see recent changes: python -m pipeline.contracts.changes
"""

import argparse
import os
from collections import Counter

from pipeline.db import connect
from pipeline.http import client
from pipeline.jobs import job_run
from pipeline.sources import require_enabled

MAX_ITEMS_PER_RUN = 200


def pending_news(conn, limit: int = MAX_ITEMS_PER_RUN, backfill: bool = False) -> list[dict]:
    cur = conn.execute(
        """select id, title, outlet, url, published_at from contract_news
           where status in ('pending', 'failed') and (query like 'backfill%%') = %s order by published_at nulls last, id limit %s""",
        (backfill, limit),
    )
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def main(argv: list[str] | None = None) -> None:
    import anthropic

    from pipeline.contracts import news
    from pipeline.contracts.apply import Applier
    from pipeline.contracts.extract import BATCH_SIZE, MODEL, extract

    parser = argparse.ArgumentParser(description="Keep contracts current from news")
    parser.add_argument("--dry-run", action="store_true", help="print what Claude extracts; change no contracts")
    parser.add_argument("--backfill", action="store_true",
                        help="process released backfill headlines: only add missing contracts, never change one")
    parser.add_argument("--max", type=int, default=MAX_ITEMS_PER_RUN, help="most headlines to process this run")
    args = parser.parse_args(argv)

    with job_run("contract_news") as counts, connect(autocommit=True) as conn, client() as http:
        require_enabled(conn, "contract_news")
        # Wait for the starting contracts: updating first would make the starting import refuse to load.
        if not conn.execute("select exists (select 1 from contracts where source = 'starting_file')").fetchone()[0]:
            counts["waiting_for_starting_file"] = 1
            print("contract news: waiting for the starting contracts (python -m pipeline.ingest.contracts). Nothing done.")
            return
        if not args.backfill:
            news.collect(conn, http, counts)
        items = pending_news(conn, args.max, args.backfill)
        counts["news_to_read"] = len(items)
        if not items:
            print(f"contract news: nothing new. {dict(counts)}")
            return
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            raise RuntimeError("ANTHROPIC_API_KEY is not set, so contract news cannot be read. Add it to .env and GitHub secrets.")

        claude = anthropic.Anthropic()
        team_codes = dict(conn.execute("select abbrev, name from teams where active").fetchall())
        teams = dict(conn.execute("select abbrev, id from teams where active").fetchall())
        applier = Applier(conn, getattr(counts, "run_id", None), MODEL, teams, create_only=args.backfill)
        outcomes: Counter = Counter()
        errors: list[str] = []

        for start in range(0, len(items), BATCH_SIZE):
            batch = items[start:start + BATCH_SIZE]
            ids = [i["id"] for i in batch]
            try:
                result = extract(claude, batch, team_codes)
            except Exception as exc:  # keep going; these headlines are retried next run
                counts["batches_failed"] += 1
                errors.append(f"{type(exc).__name__}: {exc}")
                if not args.dry_run:
                    conn.execute(
                        "update contract_news set status = 'failed', processed_at = now(), error = %s where id = any(%s)",
                        (errors[-1][:1000], ids),
                    )
                continue
            counts["input_tokens"] += result.input_tokens
            counts["output_tokens"] += result.output_tokens
            if result.stop_reason == "refusal":
                counts["batches_refused"] += 1
            for t in result.transactions:
                sources = [batch[i - 1] for i in t["items"]]
                if args.dry_run:
                    print(f"{t['status']:9} {t['type']:12} {t['player_name']:24} {t.get('team') or '':4} "
                          f"cap {t.get('cap_hit')} total {t.get('total_value')} yrs {t.get('years')} | {t['evidence']}")
                    continue
                outcome = applier.apply(t, sources)
                outcomes[outcome] += 1
            if not args.dry_run:
                conn.execute(
                    "update contract_news set status = 'extracted', processed_at = now(), error = null where id = any(%s)",
                    (ids,),
                )
        counts.update({f"events_{k}": v for k, v in outcomes.items()})
        if errors:
            raise RuntimeError(f"{len(errors)} Claude request(s) failed; they will be retried. First: {errors[0]}")
    print(f"contract news ok: {dict(counts)}")


if __name__ == "__main__":
    main()
