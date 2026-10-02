"""News collector: Google News searches and RSS feeds from beat writers and local outlets.

Stores the headline, a short snippet, the link, and the date only. Never full articles.
"""

import calendar
from datetime import UTC, datetime

import feedparser

from pipeline.http import request
from pipeline.sentiment.models import NEWS_SNIPPET, Feed, FetchResult, Mention, clip, strip_html

GOOGLE_NEWS_URL = "https://news.google.com/rss/search"


class Collector:
    source = "news_rss"
    kinds = ("rss", "google_news")

    def __init__(self, http, feeds: list[Feed]):
        self.http = http

    def unavailable(self, feed: Feed) -> str | None:
        return None

    def fetch(self, feed: Feed, cursor: str | None) -> FetchResult:
        if feed.kind == "google_news":
            # "when:2d" keeps results recent; repeats across runs are skipped on insert.
            params = {"q": f"{feed.value} when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"}
            response = request(self.http, "GET", GOOGLE_NEWS_URL, params=params)
        else:
            response = request(self.http, "GET", feed.value)
        mentions = parse_feed(response.content, feed)
        return FetchResult(mentions, {"feed": feed.value, "xml": response.text}, cursor)


def parse_feed(content: bytes, feed: Feed) -> list[Mention]:
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"could not read feed {feed.value!r}: {parsed.bozo_exception}")
    mentions = []
    for entry in parsed.entries:
        link = entry.get("link")
        item_id = entry.get("id") or link
        when = entry.get("published_parsed") or entry.get("updated_parsed")
        if not item_id or not when:
            continue
        title = strip_html(entry.get("title"))
        outlet = (entry.get("source") or {}).get("title")
        # Google News appends " - Outlet" to headlines; the outlet is kept in author instead.
        if outlet and title.endswith(f" - {outlet}"):
            title = title[: -len(f" - {outlet}")]
        snippet = strip_html(entry.get("summary"))
        # Google News summaries just repeat the headline and outlet, so drop those.
        if snippet.startswith(title):
            snippet = ""
        mentions.append(
            Mention(
                source="news_rss",
                source_item_id=item_id,
                kind="article",
                audience=feed.audience,
                posted_at=datetime.fromtimestamp(calendar.timegm(when), UTC),
                url=link,
                author=entry.get("author") or outlet,
                title=title,
                text=clip(snippet, NEWS_SNIPPET) or None,
                raw={"outlet": outlet} if outlet else {},
            )
        )
    return mentions
