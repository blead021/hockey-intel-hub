from datetime import UTC, datetime

import pytest

from pipeline.archive import archive_key
from pipeline.ingest.nhl_teams import NhlSchemaError, parse_teams
from pipeline.sentiment.bluesky import parse_post
from pipeline.sentiment.feeds import read_csv
from pipeline.sentiment.models import Feed, clip, strip_html
from pipeline.sentiment.reddit import parse_comment
from pipeline.sentiment.reddit import parse_post as parse_reddit_post
from pipeline.sentiment.rss import parse_feed
from pipeline.sentiment.youtube import parse_thread

FAN = Feed(id=1, kind="subreddit", value="canucks", team_id=23, audience="fan")
NEWS = Feed(id=2, kind="google_news", value='"Vancouver Canucks"', team_id=23, audience="media")


def test_reddit_post_tags_game_threads():
    m = parse_reddit_post(
        {
            "name": "t3_abc", "created_utc": 1759363200, "permalink": "/r/canucks/comments/abc/x/",
            "author": "fan1", "title": "Post Game Thread: Flames at Canucks", "selftext": "",
            "subreddit": "canucks", "score": 12, "num_comments": 400,
        },
        FAN,
    )
    assert m.source_item_id == "t3_abc"
    assert m.kind == "post"
    assert m.text is None
    assert m.raw["game_thread"] is True
    assert m.url == "https://www.reddit.com/r/canucks/comments/abc/x/"
    assert m.posted_at == datetime(2025, 10, 2, tzinfo=UTC)


def test_reddit_comment_skips_removed_and_keeps_thread():
    assert parse_comment({"name": "t1_x", "created_utc": 0, "permalink": "/x", "body": "[removed]"}, FAN) is None
    m = parse_comment(
        {
            "name": "t1_y", "created_utc": 1759363200, "permalink": "/r/canucks/comments/abc/x/y/",
            "body": " Hughes was great ", "link_id": "t3_abc", "link_title": "Game Thread: CGY @ VAN",
        },
        FAN,
    )
    assert m.text == "Hughes was great"
    assert m.thread_id == "t3_abc"
    assert m.raw["game_thread"] is True


def test_bluesky_post_uses_writer_list_for_audience():
    post = {
        "uri": "at://did:plc:abc/app.bsky.feed.post/3kxyz",
        "indexedAt": "2026-10-01T12:00:00.000Z",
        "author": {"handle": "writer.bsky.social"},
        "record": {"text": "Trade talk heating up", "createdAt": "2026-10-01T11:59:00.000Z"},
        "likeCount": 5,
    }
    search = Feed(id=3, kind="bluesky_search", value="Canucks", team_id=23, audience="fan")
    m = parse_post(post, search, {"writer.bsky.social"})
    assert m.audience == "beat_writer"
    assert m.url == "https://bsky.app/profile/writer.bsky.social/post/3kxyz"
    assert parse_post(post, search, set()).audience == "fan"
    assert parse_post({"record": {}}, search, set()) is None


GOOGLE_NEWS_XML = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Canucks win opener - Vancouver Sun</title><link>https://news.example/a</link>
<guid>abc123</guid><pubDate>Wed, 01 Oct 2026 03:00:00 GMT</pubDate>
<description>&lt;a href="https://news.example/a"&gt;Canucks win opener&lt;/a&gt; Vancouver Sun</description>
<source url="https://vancouversun.com">Vancouver Sun</source></item>
<item><title>No date</title><link>https://news.example/b</link></item>
</channel></rss>"""


def test_google_news_keeps_headline_only_and_skips_undated():
    [m] = parse_feed(GOOGLE_NEWS_XML, NEWS)
    assert m.title == "Canucks win opener"
    assert m.author == "Vancouver Sun"
    assert m.text is None  # the summary only repeated the headline
    assert m.source_item_id == "abc123"
    assert m.posted_at == datetime(2026, 10, 1, 3, tzinfo=UTC)


def test_bad_feed_raises():
    with pytest.raises(ValueError, match="could not read feed"):
        parse_feed(b"<html>not a feed", NEWS)


def test_youtube_thread():
    thread = {
        "snippet": {
            "videoId": "vid1",
            "totalReplyCount": 2,
            "topLevelComment": {
                "id": "c1",
                "snippet": {
                    "publishedAt": "2026-10-01T05:00:00Z", "textOriginal": "Great goal",
                    "authorDisplayName": "@fan", "likeCount": 3,
                },
            },
        }
    }
    feed = Feed(id=4, kind="youtube_channel", value="@canucks", team_id=23, audience="fan")
    m = parse_thread(thread, "Highlights", feed)
    assert m.url == "https://www.youtube.com/watch?v=vid1&lc=c1"
    assert m.title == "Highlights"
    assert m.raw == {"likes": 3, "replies": 2}


def test_text_helpers():
    assert strip_html("<b>Hi</b>&amp; there") == "Hi & there"
    assert clip("abcdef", 4) == "abc…"
    assert clip(None) is None


def test_archive_key_is_safe():
    key = archive_key("reddit", 'subreddit-r/"Odd Name"', datetime(2026, 10, 1, 5, 6, 7, tzinfo=UTC))
    assert key.startswith("raw/reddit/2026/10/01/subreddit-r-Odd-Name/050607-")
    assert key.endswith(".json.gz")


def test_feeds_csv_in_repo_is_valid():
    rows = read_csv()
    assert sum(r.kind == "subreddit" for r in rows) == 33


def test_feeds_csv_reports_all_problems(tmp_path):
    bad = tmp_path / "feeds.csv"
    bad.write_text(
        "kind,value,team,audience,label,active,notes\n"
        "subredit,canucks,VAN,fan,,yes,\n"
        "subreddit,,VAN,fans,,yes,\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as error:
        read_csv(bad)
    message = str(error.value)
    assert "line 2: unknown kind" in message
    assert "line 3: value is empty" in message
    assert "line 3: audience must be" in message


def _standings(*abbrevs):
    return {
        "standings": [
            {"teamAbbrev": {"default": a}, "teamName": {"default": a}, "conferenceName": "Western", "divisionName": "Pacific"}
            for a in abbrevs
        ]
    }


def test_parse_teams_joins_ids_and_checks_count():
    abbrevs = [f"T{i:02d}" for i in range(32)]
    team_list = {"data": [{"id": i, "triCode": a} for i, a in enumerate(abbrevs)]}
    teams = parse_teams(_standings(*abbrevs), team_list)
    assert len(teams) == 32 and teams[5].id == 5
    with pytest.raises(NhlSchemaError, match="expected 32"):
        parse_teams(_standings(*abbrevs[:31]), team_list)
    with pytest.raises(NhlSchemaError, match="missing field"):
        parse_teams({"standings": [{"teamAbbrev": {}}]}, team_list)
