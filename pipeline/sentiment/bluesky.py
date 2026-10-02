"""Bluesky collector: posts from curated beat writers and insiders, plus keyword searches.

Account feeds are public. Search needs a Bluesky login (handle plus an app password).
"""

import os
from datetime import UTC, datetime, timedelta

from pipeline.http import get_json, request
from pipeline.sentiment.models import Feed, FetchResult, Mention, from_iso

PUBLIC_API = "https://public.api.bsky.app/xrpc"
PDS_API = "https://bsky.social/xrpc"
MAX_PAGES = 5
FIRST_RUN_LOOKBACK = timedelta(days=2)


class Collector:
    source = "bluesky"
    kinds = ("bluesky_account", "bluesky_search")

    def __init__(self, http, feeds: list[Feed]):
        self.http = http
        # Posts by curated accounts count as beat_writer even when found by search.
        self.writers = {f.value for f in feeds if f.kind == "bluesky_account"}
        self._token: str | None = None

    def unavailable(self, feed: Feed) -> str | None:
        if feed.kind == "bluesky_search" and not (
            os.environ.get("BLUESKY_HANDLE") and os.environ.get("BLUESKY_APP_PASSWORD")
        ):
            return "BLUESKY_HANDLE and BLUESKY_APP_PASSWORD are not set"
        return None

    def fetch(self, feed: Feed, cursor: str | None) -> FetchResult:
        since = from_iso(cursor) if cursor else datetime.now(UTC) - FIRST_RUN_LOOKBACK
        if feed.kind == "bluesky_account":
            pages = self._author_pages(feed.value, since)
            items = [i for page in pages for i in page.get("feed", []) if "reason" not in i]  # skip reposts
            posts = [i["post"] for i in items]
        else:
            pages = self._search_pages(feed.value, since)
            posts = [p for page in pages for p in page.get("posts", [])]

        mentions = [parse_post(p, feed, self.writers) for p in posts]
        mentions = [m for m in mentions if m and m.posted_at >= since - timedelta(hours=1)]
        newest = max((m.raw["indexed_at"] for m in mentions), default=cursor)
        return FetchResult(mentions, pages, newest)

    def _author_pages(self, handle: str, since: datetime) -> list[dict]:
        pages, page_cursor = [], None
        for _ in range(MAX_PAGES):
            params = {"actor": handle, "limit": 100, "filter": "posts_with_replies"}
            if page_cursor:
                params["cursor"] = page_cursor
            page = get_json(self.http, f"{PUBLIC_API}/app.bsky.feed.getAuthorFeed", params=params)
            pages.append(page)
            items = page.get("feed", [])
            page_cursor = page.get("cursor")
            oldest = min((from_iso(i["post"]["indexedAt"]) for i in items), default=None)
            if not page_cursor or oldest is None or oldest <= since:
                break
        return pages

    def _search_pages(self, query: str, since: datetime) -> list[dict]:
        pages, page_cursor = [], None
        headers = {"Authorization": f"Bearer {self._login()}"}
        for _ in range(MAX_PAGES):
            params = {"q": query, "sort": "latest", "since": since.isoformat(), "limit": 100}
            if page_cursor:
                params["cursor"] = page_cursor
            page = get_json(self.http, f"{PDS_API}/app.bsky.feed.searchPosts", params=params, headers=headers)
            pages.append(page)
            page_cursor = page.get("cursor")
            if not page_cursor or not page.get("posts"):
                break
        return pages

    def _login(self) -> str:
        if self._token is None:
            response = request(
                self.http,
                "POST",
                f"{PDS_API}/com.atproto.server.createSession",
                json={
                    "identifier": os.environ["BLUESKY_HANDLE"],
                    "password": os.environ["BLUESKY_APP_PASSWORD"],
                },
            )
            self._token = response.json()["accessJwt"]
        return self._token


def parse_post(post: dict, feed: Feed, writers: set[str]) -> Mention | None:
    record = post.get("record") or {}
    handle = (post.get("author") or {}).get("handle", "")
    uri = post.get("uri", "")
    if not uri or "indexedAt" not in post:
        return None
    try:
        posted_at = from_iso(record["createdAt"])
    except (KeyError, ValueError):
        posted_at = from_iso(post["indexedAt"])
    rkey = uri.rsplit("/", 1)[-1]
    audience = "beat_writer" if handle.lower() in writers else feed.audience
    return Mention(
        source="bluesky",
        source_item_id=uri,
        kind="post",
        audience=audience,
        posted_at=posted_at,
        url=f"https://bsky.app/profile/{handle}/post/{rkey}",
        author=handle,
        text=record.get("text"),
        thread_id=((record.get("reply") or {}).get("root") or {}).get("uri"),
        raw={
            "indexed_at": post["indexedAt"],
            "likes": post.get("likeCount", 0),
            "reposts": post.get("repostCount", 0),
            "replies": post.get("replyCount", 0),
        },
    )
