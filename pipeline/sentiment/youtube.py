"""YouTube collector: recent videos (as media mentions) and their viewer comments (as fan mentions).

Uses the YouTube Data API with an API key. The free quota is 10,000 units a day. Every call here
costs 1 unit, and comments are only fetched for videos whose comment count went up since the
last run. Search calls cost 100 units, so this collector never uses them.
"""

import json
import os
from datetime import UTC, datetime, timedelta

from pipeline.http import HttpError, get_json
from pipeline.sentiment.models import NEWS_SNIPPET, Feed, FetchResult, Mention, clip, from_iso

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
        known = state.get("videos", {})  # video id -> {"count": comments seen, "since": newest comment time}

        playlist = self._get("playlistItems", part="snippet,contentDetails", playlistId=uploads, maxResults=MAX_VIDEOS)
        cutoff = datetime.now(UTC) - VIDEO_WINDOW
        recent = [
            item
            for item in playlist.get("items", [])
            if _published(item) >= cutoff
        ]
        payload, mentions, videos_state = {"playlist": playlist, "stats": None, "comments": {}}, [], {}
        if not recent:
            return FetchResult(mentions, payload, json.dumps({"uploads": uploads, "videos": {}}))

        ids = [item["contentDetails"]["videoId"] for item in recent]
        stats = self._get("videos", part="statistics", id=",".join(ids))
        payload["stats"] = stats
        counts = {v["id"]: int(v["statistics"].get("commentCount", 0)) for v in stats.get("items", [])}

        for item in recent:
            video_id = item["contentDetails"]["videoId"]
            mentions.append(parse_video(item, counts.get(video_id), feed))
            previous = known.get(video_id, {})
            since = from_iso(previous["since"]) if previous.get("since") else _published(item) - timedelta(minutes=1)
            entry = {"count": previous.get("count", 0), "since": since.isoformat()}
            if counts.get(video_id, 0) > entry["count"]:
                pages = self._comment_pages(video_id, since)
                payload["comments"][video_id] = pages
                new = [
                    m
                    for page in pages
                    for thread in page.get("items", [])
                    if (m := parse_thread(thread, item["snippet"]["title"])).posted_at > since
                ]
                mentions.extend(new)
                entry = {
                    "count": counts[video_id],
                    "since": max((m.posted_at for m in new), default=since).isoformat(),
                }
            videos_state[video_id] = entry

        return FetchResult(mentions, payload, json.dumps({"uploads": uploads, "videos": videos_state}))

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


def _published(item: dict) -> datetime:
    return from_iso(item["contentDetails"].get("videoPublishedAt") or item["snippet"]["publishedAt"])


def parse_video(item: dict, comment_count: int | None, feed: Feed) -> Mention:
    snippet = item["snippet"]
    video_id = item["contentDetails"]["videoId"]
    return Mention(
        source="youtube",
        source_item_id=f"video:{video_id}",
        kind="post",
        audience=feed.audience,
        posted_at=_published(item),
        url=f"https://www.youtube.com/watch?v={video_id}",
        author=snippet.get("channelTitle"),
        title=snippet.get("title"),
        text=clip(snippet.get("description"), NEWS_SNIPPET) or None,
        thread_id=video_id,
        raw={"channel": feed.value, "comments": comment_count},
    )


def parse_thread(thread: dict, video_title: str) -> Mention:
    """Viewer comments are fan voices, whatever kind of channel they were left on."""
    top = thread["snippet"]["topLevelComment"]
    snippet = top["snippet"]
    video_id = thread["snippet"]["videoId"]
    return Mention(
        source="youtube",
        source_item_id=top["id"],
        kind="comment",
        audience="fan",
        posted_at=from_iso(snippet["publishedAt"]),
        url=f"https://www.youtube.com/watch?v={video_id}&lc={top['id']}",
        author=snippet.get("authorDisplayName"),
        title=video_title,
        text=snippet.get("textOriginal") or snippet.get("textDisplay"),
        thread_id=video_id,
        raw={"likes": snippet.get("likeCount", 0), "replies": thread["snippet"].get("totalReplyCount", 0)},
    )
