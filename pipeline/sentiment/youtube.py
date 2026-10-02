"""YouTube collector: top-level comments on recent videos from team channels.

Uses the YouTube Data API with an API key. Each call here costs 1 quota unit (the free quota
is 10,000 a day). Search calls cost 100 units, so this collector never uses them.
"""

import json
import os
from datetime import UTC, datetime, timedelta

from pipeline.http import HttpError, get_json
from pipeline.sentiment.models import Feed, FetchResult, Mention, from_iso

API = "https://www.googleapis.com/youtube/v3"
VIDEO_WINDOW = timedelta(days=7)
MAX_VIDEOS = 10
PAGES_PER_VIDEO = 3


class Collector:
    source = "youtube"
    kinds = ("youtube_channel",)

    def __init__(self, http, feeds: list[Feed]):
        self.http = http

    def unavailable(self, feed: Feed) -> str | None:
        return None if os.environ.get("YOUTUBE_API_KEY") else "YOUTUBE_API_KEY is not set"

    def fetch(self, feed: Feed, cursor: str | None) -> FetchResult:
        state = json.loads(cursor) if cursor else {}
        uploads = state.get("uploads") or self._uploads_playlist(feed.value)
        since = from_iso(state["since"]) if state.get("since") else datetime.now(UTC) - timedelta(days=2)

        playlist = self._get("playlistItems", part="snippet,contentDetails", playlistId=uploads, maxResults=MAX_VIDEOS)
        cutoff = datetime.now(UTC) - VIDEO_WINDOW
        videos = [
            (item["contentDetails"]["videoId"], item["snippet"]["title"])
            for item in playlist.get("items", [])
            if from_iso(item["contentDetails"].get("videoPublishedAt") or item["snippet"]["publishedAt"]) >= cutoff
        ]

        payload, mentions = {"playlist": playlist, "comments": {}}, []
        for video_id, title in videos:
            pages = self._comment_pages(video_id, since)
            payload["comments"][video_id] = pages
            for page in pages:
                for thread in page.get("items", []):
                    m = parse_thread(thread, title, feed)
                    if m.posted_at > since:
                        mentions.append(m)

        newest = max((m.posted_at for m in mentions), default=since)
        return FetchResult(mentions, payload, json.dumps({"uploads": uploads, "since": newest.isoformat()}))

    def _uploads_playlist(self, channel: str) -> str:
        lookup = {"id": channel} if channel.startswith("UC") else {"forHandle": channel}
        body = self._get("channels", part="contentDetails", **lookup)
        if not body.get("items"):
            raise ValueError(f"YouTube channel {channel!r} was not found")
        return body["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    def _comment_pages(self, video_id: str, since: datetime) -> list[dict]:
        pages, token = [], None
        for _ in range(PAGES_PER_VIDEO):
            params = {"part": "snippet", "videoId": video_id, "order": "time", "maxResults": 100, "textFormat": "plainText"}
            if token:
                params["pageToken"] = token
            try:
                page = self._get("commentThreads", **params)
            except HttpError as exc:
                if exc.status == 403 and "commentsDisabled" in exc.body:
                    return pages
                raise
            pages.append(page)
            token = page.get("nextPageToken")
            items = page.get("items", [])
            oldest = min((from_iso(i["snippet"]["topLevelComment"]["snippet"]["publishedAt"]) for i in items), default=None)
            if not token or oldest is None or oldest <= since:
                break
        return pages

    def _get(self, resource: str, **params) -> dict:
        return get_json(self.http, f"{API}/{resource}", params={**params, "key": os.environ["YOUTUBE_API_KEY"]})


def parse_thread(thread: dict, video_title: str, feed: Feed) -> Mention:
    top = thread["snippet"]["topLevelComment"]
    snippet = top["snippet"]
    video_id = thread["snippet"]["videoId"]
    return Mention(
        source="youtube",
        source_item_id=top["id"],
        kind="comment",
        audience=feed.audience,
        posted_at=from_iso(snippet["publishedAt"]),
        url=f"https://www.youtube.com/watch?v={video_id}&lc={top['id']}",
        author=snippet.get("authorDisplayName"),
        title=video_title,
        text=snippet.get("textOriginal") or snippet.get("textDisplay"),
        thread_id=video_id,
        raw={"likes": snippet.get("likeCount", 0), "replies": thread["snippet"].get("totalReplyCount", 0)},
    )
