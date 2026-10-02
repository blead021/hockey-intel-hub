"""Reddit collector: new posts and comments from r/hockey and the 32 team subreddits.

Uses Reddit's official API with an app-only login (client id and secret). Game threads and
post-game threads are tagged in raw so later scoring can weight them.
"""

import json
import os
import re
import time
from datetime import UTC, datetime, timedelta

from pipeline.http import HttpError, request
from pipeline.sentiment.models import Feed, FetchResult, Mention, from_unix

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"
POST_PAGES = 3
COMMENT_PAGES = 10
FIRST_RUN_LOOKBACK = timedelta(hours=6)
GAME_THREAD = re.compile(r"\b(pre-?game|post-?game|game)\s+thread\b", re.IGNORECASE)
SKIP_BODIES = {"[removed]", "[deleted]", ""}


class Collector:
    source = "reddit"
    kinds = ("subreddit",)

    def __init__(self, http, feeds: list[Feed]):
        self.http = http
        self._token: str | None = None
        self._token_expires = 0.0

    def unavailable(self, feed: Feed) -> str | None:
        missing = [n for n in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT") if not os.environ.get(n)]
        return f"{', '.join(missing)} not set" if missing else None

    def fetch(self, feed: Feed, cursor: str | None) -> FetchResult:
        state = json.loads(cursor) if cursor else {}
        default_since = (datetime.now(UTC) - FIRST_RUN_LOOKBACK).timestamp()
        post_since = state.get("post", default_since)
        comment_since = state.get("comment", default_since)

        post_pages = self._listing(f"/r/{feed.value}/new", post_since, POST_PAGES)
        comment_pages = self._listing(f"/r/{feed.value}/comments", comment_since, COMMENT_PAGES)

        mentions = []
        for child in _children(post_pages):
            if child["kind"] == "t3" and child["data"]["created_utc"] > post_since:
                mentions.append(parse_post(child["data"], feed))
        for child in _children(comment_pages):
            if child["kind"] == "t1" and child["data"]["created_utc"] > comment_since:
                m = parse_comment(child["data"], feed)
                if m:
                    mentions.append(m)

        new_state = {
            "post": max([c["data"]["created_utc"] for c in _children(post_pages)], default=post_since),
            "comment": max([c["data"]["created_utc"] for c in _children(comment_pages)], default=comment_since),
        }
        return FetchResult(mentions, {"posts": post_pages, "comments": comment_pages}, json.dumps(new_state))

    def _listing(self, path: str, since: float, max_pages: int) -> list[dict]:
        pages, after = [], None
        for _ in range(max_pages):
            params = {"limit": 100, "raw_json": 1}
            if after:
                params["after"] = after
            page = self._get(path, params)
            if page.get("kind") != "Listing":
                raise ValueError(f"{path} did not return a listing; the subreddit may not exist")
            pages.append(page)
            children = page["data"]["children"]
            after = page["data"].get("after")
            oldest = min((c["data"]["created_utc"] for c in children), default=None)
            if not after or oldest is None or oldest <= since:
                break
        return pages

    def _get(self, path: str, params: dict) -> dict:
        headers = {"Authorization": f"Bearer {self._login()}", "User-Agent": os.environ["REDDIT_USER_AGENT"]}
        try:
            response = request(self.http, "GET", f"{API}{path}", params=params, headers=headers, follow_redirects=False)
        except HttpError as exc:
            if exc.status in (403, 404):
                raise ValueError(f"{path} returned {exc.status}; the subreddit may be private, banned, or misspelled") from None
            raise
        if response.is_redirect:
            raise ValueError(f"{path} redirected; the subreddit probably does not exist")
        _respect_rate_limit(response.headers)
        return response.json()

    def _login(self) -> str:
        if self._token is None or time.time() > self._token_expires - 60:
            response = request(
                self.http,
                "POST",
                TOKEN_URL,
                auth=(os.environ["REDDIT_CLIENT_ID"], os.environ["REDDIT_CLIENT_SECRET"]),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": os.environ["REDDIT_USER_AGENT"]},
            )
            body = response.json()
            if "access_token" not in body:
                raise ValueError(f"Reddit login failed: {body.get('error', 'no access token returned')}")
            self._token = body["access_token"]
            self._token_expires = time.time() + body.get("expires_in", 3600)
        return self._token


def _children(pages: list[dict]) -> list[dict]:
    return [c for page in pages for c in page["data"]["children"]]


def _respect_rate_limit(headers) -> None:
    """Reddit allows about 100 requests a minute; pause when the remaining budget runs low."""
    try:
        remaining = float(headers.get("x-ratelimit-remaining", "100"))
        reset = float(headers.get("x-ratelimit-reset", "0"))
    except ValueError:
        return
    if remaining < 3:
        time.sleep(min(reset + 1, 120))


def parse_post(data: dict, feed: Feed) -> Mention:
    return Mention(
        source="reddit",
        source_item_id=data["name"],
        kind="post",
        audience=feed.audience,
        posted_at=from_unix(data["created_utc"]),
        url=f"https://www.reddit.com{data['permalink']}",
        author=data.get("author"),
        title=data.get("title"),
        text=None if data.get("selftext") in SKIP_BODIES else data.get("selftext"),
        thread_id=data["name"],
        raw={
            "subreddit": data.get("subreddit"),
            "score": data.get("score"),
            "num_comments": data.get("num_comments"),
            "flair": data.get("link_flair_text"),
            "game_thread": bool(GAME_THREAD.search(data.get("title") or "")),
        },
    )


def parse_comment(data: dict, feed: Feed) -> Mention | None:
    body = (data.get("body") or "").strip()
    if body in SKIP_BODIES:
        return None
    return Mention(
        source="reddit",
        source_item_id=data["name"],
        kind="comment",
        audience=feed.audience,
        posted_at=from_unix(data["created_utc"]),
        url=f"https://www.reddit.com{data['permalink']}",
        author=data.get("author"),
        title=data.get("link_title"),
        text=body,
        thread_id=data.get("link_id"),
        raw={
            "subreddit": data.get("subreddit"),
            "score": data.get("score"),
            "parent_id": data.get("parent_id"),
            "flair": data.get("author_flair_text"),
            "game_thread": bool(GAME_THREAD.search(data.get("link_title") or "")),
        },
    )
