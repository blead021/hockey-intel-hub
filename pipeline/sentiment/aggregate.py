"""Turns scored mentions into daily sentiment per player and audience (CLAUDE.md section 6).

Usage:
    python -m pipeline.sentiment.aggregate                 the last 3 days (scores can arrive a day late)
    python -m pipeline.sentiment.aggregate --days 60       rebuild further back

score = 50 + 50 x recency-weighted mean sentiment over the last 28 days, with a 7-day half-life,
shown only when the window has at least MIN_MENTIONS scored mentions. Audiences: fan, beat_writer,
media, and all of them together. Trend (14-day change), trade chatter, and spikes are read from
sentiment_daily and the trade_chatter view.
"""

import argparse
import math
from collections import defaultdict
from datetime import date, timedelta

from pipeline.db import connect
from pipeline.jobs import job_run

WINDOW_DAYS = 28
HALF_LIFE_DAYS = 7
MIN_MENTIONS = 5


def weight(age_days: float) -> float:
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def daily_scores(mentions: list[tuple[int, str, date, float, bool]], days: list[date]) -> list[tuple]:
    """mentions: (player_id, audience, posted date, sentiment, is_trade). Returns sentiment_daily rows."""
    by_key: dict[tuple[int, str], list[tuple[date, float, bool]]] = defaultdict(list)
    for player, audience, posted, sentiment, trade in mentions:
        by_key[(player, audience)].append((posted, sentiment, trade))
        by_key[(player, "all")].append((posted, sentiment, trade))
    rows = []
    for (player, audience), items in by_key.items():
        for day in days:
            window = [(d, s, t) for d, s, t in items if day - timedelta(days=WINDOW_DAYS) < d <= day]
            if not window:
                continue
            total_w = sum(weight((day - d).days) for d, _, _ in window)
            mean = sum(weight((day - d).days) * s for d, s, _ in window) / total_w
            score = round(50 + 50 * mean, 2) if len(window) >= MIN_MENTIONS else None
            today = [(s, t) for d, s, t in window if d == day]
            rows.append((player, day, audience, score, len(today), len(window), sum(1 for _, t in today if t)))
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Daily sentiment per player and audience")
    parser.add_argument("--days", type=int, default=3)
    args = parser.parse_args(argv)
    end = date.today()
    days = [end - timedelta(days=i) for i in range(args.days)]
    start = min(days) - timedelta(days=WINDOW_DAYS)
    with job_run("sentiment_aggregate") as counts, connect() as conn:
        mentions = [
            (pid, aud, posted, float(s), bool(t))
            for pid, aud, posted, s, t in conn.execute(
                """select mp.player_id, m.audience, (m.posted_at at time zone 'UTC')::date, mp.sentiment, coalesce(mp.is_trade_related, false)
                   from mention_players mp join mentions m on m.id = mp.mention_id
                   where mp.status = 'matched' and mp.scored_at is not null and m.posted_at >= %s""",
                (start,),
            )
        ]
        rows = daily_scores(mentions, days)
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("delete from sentiment_daily where date = any(%s)", (days,))
            cur.executemany(
                """insert into sentiment_daily (player_id, date, audience, score_0_100, n_mentions, window_mentions, trade_mentions)
                   values (%s, %s, %s, %s, %s, %s, %s)""",
                rows,
            )
        counts["rows"] = len(rows)
        counts["scored_mentions_in_window"] = len(mentions)
    print(f"aggregate ok: {dict(counts)}")


if __name__ == "__main__":
    main()
