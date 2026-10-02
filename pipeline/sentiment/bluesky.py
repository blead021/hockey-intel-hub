"""Bluesky collector: beat writers and insiders, starter packs of hockey writers, and keyword searches.

Account and starter pack feeds are public. Search needs a Bluesky login (handle plus an app password).
"""

import json
import os
import re
from datetime import UTC, datetime, timedelta

from pipeline.http import get_json, request
from pipeline.sentiment.models import Feed, FetchResult, Mention, from_iso

PUBLIC_API = "https://public.api.bsky.app/xrpc"
PDS_API = "https://bsky.social/xrpc"
MAX_PAGES = 5
MAX_LIST_PAGES = 10  # a busy starter pack posts several hundred times between runs
FIRST_RUN_LOOKBACK = timedelta(days=2)
STARTER_PACK_URL = re.compile(r"^https://bsky\.app/starter-pack/([^/]+)/([^/?#]+)")


class Collector:
    source = "bluesky"
    kinds = ("bluesky_account", "bluesky_starter_pack", "bluesky_search")

    def __init__(self, http, feeds: list[Feed]):
        self.http = http
        self._accounts = {f.value for f in feeds if f.kind == "bluesky_account"}
        # Only writer packs mark their members as beat_writer; fan community packs do not.
        self._packs = [f.value for f in feeds if f.kind == "bluesky_starter_pack" and f.audience == "beat_writer"]
        self._writers: set[str] | None = None
        self._token: str | None = None

    @property
    def writers(self) -> set[str]:
        """Handles counted as beat_writer wherever they appear, including in search results."""
        if self._writers is None:
            writers = set(self._accounts)
            for pack in self._packs:
                try:
                    writers |= self._pack_members(self._pack_list(pack))
                except Exception as exc:  # a broken pack should not block search tagging
                    print(f"[bluesky] could not read members of {pack}: {exc}")
            self._writers = writers
        return self._writers

    def unavailable(self, feed: Feed) -> str | None:
        if feed.kind == "bluesky_search" and not (
            os.environ.get("BLUESKY_HANDLE") and os.environ.get("BLUESKY_APP_PASSWORD")
        ):
            return "BLUESKY_HANDLE and BLUESKY_APP_PASSWORD are not set"
        return None

    def fetch(self, feed: Feed, cursor: str | None) -> FetchResult:
        state = _read_cursor(cursor)
        since = from_iso(state["since"]) if state.get("since") else datetime.now(UTC) - FIRST_RUN_LOOKBACK

        if feed.kind == "bluesky_account":
            pages = self._feed_pages("app.bsky.feed.getAuthorFeed", {"actor": feed.value, "filter": "posts_with_replies"}, since, MAX_PAGES)
            posts = [i["post"] for page in pages for i in page.get("feed", []) if "reason" not in i]  # skip reposts
        elif feed.kind == "bluesky_starter_pack":
            state["list"] = state.get("list") or self._pack_list(feed.value)
            pages = self._feed_pages("app.bsky.feed.getListFeed", {"list": state["list"]}, since, MAX_LIST_PAGES)
            posts = [i["post"] for page in pages for i in page.get("feed", []) if "reason" not in i]
        else:
            pages = self._search_pages(feed.value, since)
            posts = [p for page in pages for p in page.get("posts", [])]

        mentions = [parse_post(p, feed, self.writers) for p in posts]
        mentions = [m for m in mentions if m and m.posted_at >= since - timedelta(hours=1)]
        newest = max((m.raw["indexed_at"] for m in mentions), default=state.get("since"))
        state["since"] = newest
        return FetchResult(mentions, pages, json.dumps(state))

    def _feed_pages(self, method: str, params: dict, since: datetime, max_pages: int) -> list[dict]:
        pages, page_cursor = [], None
        for _ in range(max_pages):
            query = {**params, "limit": 100}
            if page_cursor:
                query["cursor"] = page_cursor
            page = get_json(self.http, f"{PUBLIC_API}/{method}", params=query)
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

    def _pack_list(self, pack_url: str) -> str:
        """Turns a starter pack link into the AT URI of the list of people in it."""
        match = STARTER_PACK_URL.match(pack_url)
        if not match:
            raise ValueError(f"not a starter pack link: {pack_url!r}")
        handle, rkey = match.groups()
        body = get_json(
            self.http,
            f"{PUBLIC_API}/app.bsky.graph.getStarterPack",
            params={"starterPack": f"at://{handle}/app.bsky.graph.starterpack/{rkey}"},
        )
        return body["starterPack"]["list"]["uri"]

    def _pack_members(self, list_uri: str) -> set[str]:
        members, page_cursor = set(), None
        while True:
            params = {"list": list_uri, "limit": 100}
            if page_cursor:
                params["cursor"] = page_cursor
            page = get_json(self.http, f"{PUBLIC_API}/app.bsky.graph.getList", params=params)
            items = page.get("items", [])
            members |= {i["subject"]["handle"].lower() for i in items}
            page_cursor = page.get("cursor")
            if not page_cursor or not items:
                return members

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


def _read_cursor(cursor: str | None) -> dict:
    """Cursors are JSON. Older ones were a bare timestamp, so accept those too."""
    if not cursor:
        return {}
    if cursor.startswith("{"):
        return json.loads(cursor)
    return {"since": cursor}


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
