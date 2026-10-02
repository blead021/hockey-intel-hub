"""Shared types for the sentiment collectors."""

import html
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

MAX_TEXT = 5000
NEWS_SNIPPET = 300


@dataclass(frozen=True)
class Feed:
    id: int
    kind: str
    value: str
    team_id: int | None
    audience: str
    label: str | None = None


@dataclass
class Mention:
    source: str
    source_item_id: str
    kind: str
    audience: str
    posted_at: datetime
    url: str | None = None
    author: str | None = None
    title: str | None = None
    text: str | None = None
    thread_id: str | None = None
    team_id: int | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class FetchResult:
    mentions: list[Mention]
    payload: object  # full API response(s), archived to R2 as-is
    cursor: str | None  # where the next run should pick up


def clip(text: str | None, limit: int = MAX_TEXT) -> str | None:
    if text is None:
        return None
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def from_unix(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, UTC)


def from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def save_mentions(conn, feed: Feed, mentions: list[Mention], archive_key: str | None) -> int:
    """Inserts new mentions in one batch and returns how many were new. Items already stored are skipped."""
    if not mentions:
        return 0
    rows = [
        (
            m.source, m.source_item_id, feed.id, m.kind, m.audience,
            m.team_id if m.team_id is not None else feed.team_id,
            m.url, m.author, m.posted_at, clip(m.title, 500), clip(m.text), m.thread_id,
            Jsonb(m.raw), archive_key,
        )
        for m in mentions
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """insert into mentions (source, source_item_id, feed_id, kind, audience, team_id, url,
                   author, posted_at, title, text, thread_id, raw, archive_key)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (source, source_item_id) do nothing""",
            rows,
        )
        return cur.rowcount
