"""Runs the sentiment collectors and stores what they find.

Usage:
    python -m pipeline.sentiment.collect                 all sources
    python -m pipeline.sentiment.collect --source reddit one source (news_rss, bluesky, reddit, youtube)

For each feed: fetch new items, save the full response to R2, then insert new mentions.
The R2 copy is written first, so nothing is lost if the database insert fails.
One failing feed is logged and skipped. A source fails the job only when most of its feeds fail.
"""

import argparse
import sys
import traceback

from pipeline import archive
from pipeline.db import connect
from pipeline.http import client
from pipeline.jobs import job_run
from pipeline.sentiment import bluesky, reddit, rss, youtube
from pipeline.sentiment.models import Feed, save_mentions
from pipeline.sources import is_enabled

COLLECTORS = {c.Collector.source: c.Collector for c in (rss, bluesky, reddit, youtube)}


class SourceFailed(RuntimeError):
    pass


def load_feeds(conn, kinds: tuple[str, ...]) -> list[Feed]:
    rows = conn.execute(
        "select id, kind, value, team_id, audience, label from sentiment_feeds where active and kind = any(%s) order by id",
        (list(kinds),),
    ).fetchall()
    return [Feed(*row) for row in rows]


def load_cursor(conn, feed_id: int) -> str | None:
    row = conn.execute("select cursor from collector_state where feed_id = %s", (feed_id,)).fetchone()
    return row[0] if row else None


def record_state(conn, feed_id: int, cursor: str | None = None, error: str | None = None) -> None:
    if error is None:
        conn.execute(
            """insert into collector_state (feed_id, cursor, last_run_at, last_success_at, last_error, consecutive_failures)
               values (%s, %s, now(), now(), null, 0)
               on conflict (feed_id) do update set cursor = excluded.cursor, last_run_at = now(),
                 last_success_at = now(), last_error = null, consecutive_failures = 0""",
            (feed_id, cursor),
        )
    else:
        conn.execute(
            """insert into collector_state (feed_id, last_run_at, last_error, consecutive_failures)
               values (%s, now(), %s, 1)
               on conflict (feed_id) do update set last_run_at = now(), last_error = excluded.last_error,
                 consecutive_failures = collector_state.consecutive_failures + 1""",
            (feed_id, error[:2000]),
        )


def run_source(conn, http, source: str, counts) -> None:
    if not is_enabled(conn, source):
        counts[f"{source}_switched_off"] = 1
        return
    collector_cls = COLLECTORS[source]
    feeds = load_feeds(conn, collector_cls.kinds)
    collector = collector_cls(http, feeds)
    attempted = failed = 0

    for feed in feeds:
        reason = collector.unavailable(feed)
        if reason:
            counts[f"{source}_feeds_skipped"] += 1
            counts.setdefault(f"{source}_skip_reason", reason)
            continue
        attempted += 1
        try:
            result = collector.fetch(feed, load_cursor(conn, feed.id))
            key = archive.save(source, f"{feed.kind}-{feed.value}", result.payload)
            with conn.transaction():
                new = save_mentions(conn, feed, result.mentions, key)
                record_state(conn, feed.id, result.cursor)
            counts[f"{source}_mentions_new"] += new
            counts[f"{source}_mentions_seen"] += len(result.mentions)
            if key:
                counts["archived"] += 1
        except archive.ArchiveUnavailable:
            raise  # a setup problem, not a feed problem: stop the whole job
        except Exception as exc:  # one bad feed must not stop the others
            failed += 1
            counts[f"{source}_feeds_failed"] += 1
            message = f"{type(exc).__name__}: {exc}"
            print(f"[{source}] {feed.kind} {feed.value}: {message}", file=sys.stderr)
            with conn.transaction():
                record_state(conn, feed.id, error=message + "\n" + traceback.format_exc(limit=5))

    if attempted and failed / attempted > 0.5:
        raise SourceFailed(f"{source}: {failed} of {attempted} feeds failed; see collector_state.last_error")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=[*COLLECTORS, "all"], default="all")
    args = parser.parse_args(argv)
    sources = list(COLLECTORS) if args.source == "all" else [args.source]

    with job_run(f"collect_{args.source}") as counts, connect(autocommit=True) as conn, client() as http:
        failures = []
        for source in sources:
            try:
                run_source(conn, http, source, counts)
            except SourceFailed as exc:
                failures.append(str(exc))
        if failures:
            raise SourceFailed("; ".join(failures))
    print(f"collect ok: {dict(counts)}")


if __name__ == "__main__":
    main()
