"""Adds Brian's fan source list (blogs, podcasts, YouTube channels) to feeds.csv.

Usage:
    python -m pipeline.sentiment.import_sources NHL_fan_sources_third_pass-6442a56a.xlsx
    then: python -m pipeline.sentiment.feeds   (load feeds.csv into the database)

Reads the "Sources" tab (Team, Name, Type, URL, Status, Notes). For each row:
- YouTube: the @handle or channel id from the link (custom /c/ links cannot be resolved for free; reported).
- Blogs, sites, podcasts: the RSS or Atom feed, found from the page's own feed link or the usual feed paths,
  or for Apple Podcasts through Apple's free lookup service; kept only if the feed parses with entries.
- X accounts, subreddits, and forums are skipped (no affordable API, Reddit is off, forum terms).
Audience: official team channels and news or analysis sites are media; blogs, podcasts, and fan channels are fan.
Nothing already in feeds.csv is added twice. Headlines, snippets, and comments only, as for every feed.
"""

import argparse
import csv
import unicodedata
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser

import httpx

from pipeline.db import connect
from pipeline.http import USER_AGENT
from pipeline.sentiment.feeds import CSV_PATH

# Discovery uses quick, single requests: no retries and no honoring "come back later" waits, so one slow or
# unfriendly site cannot hold up the list (the shared client waits politely, which suits the collectors).
TIMEOUT = httpx.Timeout(12.0, connect=8.0)


def get(http, url: str, **params):
    response = http.get(url, params=params or None)
    response.raise_for_status()
    return response

FEED_LINK = re.compile(r"""<link[^>]+type=["']application/(?:rss|atom)\+xml["'][^>]*>""", re.IGNORECASE)
HREF = re.compile(r"""href=["']([^"']+)["']""", re.IGNORECASE)
COMMON_PATHS = ("/feed", "/feed/", "/rss", "/rss/index.xml", "/index.xml", "/feed.xml", "/rss.xml", "/atom.xml")
SKIP_TYPES = ("x ", "x beat", "subreddit", "forum", "community")
MEDIA_TYPES = ("official", "news", "analysis")


def plain(text: str) -> str:
    """Lowercase without accents, so "Montreal Canadiens" matches "Montréal Canadiens"."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower().strip()


def feed_ok(http, url: str) -> bool:
    try:
        response = get(http, url)
    except Exception:
        return False
    parsed = feedparser.parse(response.content)
    return bool(parsed.entries)


def discover_feed(http, url: str) -> str | None:
    if "podcasts.apple.com" in url:
        m = re.search(r"/id(\d+)", url)
        if not m:
            return None
        try:
            body = get(http, "https://itunes.apple.com/lookup", id=m.group(1)).json()
        except Exception:
            return None
        feed = next((r.get("feedUrl") for r in body.get("results", []) if r.get("feedUrl")), None)
        return feed if feed and feed_ok(http, feed) else None
    try:
        page = get(http, url)
        html = page.text
    except Exception:
        html = ""
    for tag in FEED_LINK.findall(html):
        href = HREF.search(tag)
        if href:
            candidate = urljoin(url, href.group(1))
            if "comments" not in candidate and feed_ok(http, candidate):
                return candidate
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    for path in COMMON_PATHS:
        if feed_ok(http, base + path):
            return base + path
    return None


def youtube_value(url: str) -> str | None:
    m = re.search(r"youtube\.com/(@[\w.\-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"youtube\.com/channel/(UC[\w\-]+)", url)
    return m.group(1) if m else None


def main(argv: list[str] | None = None) -> None:
    import openpyxl

    parser = argparse.ArgumentParser(description="Add fan sources from Brian's spreadsheet to feeds.csv")
    parser.add_argument("path", type=Path)
    parser.add_argument("--team", help="only this team's rows (full name), for a re-run")
    args = parser.parse_args(argv)

    wb = openpyxl.load_workbook(args.path, read_only=True, data_only=True)
    rows = [r for r in wb["Sources"].iter_rows(min_row=2, values_only=True) if r and r[0] and r[3]]
    with connect() as conn:
        teams = {plain(name): code for code, name in conn.execute("select abbrev, name from teams where active")}
    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        existing = list(csv.DictReader(f))
    have = {(r["kind"], r["value"].lower().rstrip("/")) for r in existing}

    added, skipped, failed = [], [], []
    out = open(CSV_PATH, "a", encoding="utf-8", newline="")
    writer = csv.DictWriter(out, fieldnames=["kind", "value", "team", "audience", "label", "active", "notes"])
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=True) as http:
        for team, name, kind, url, status, notes in (tuple(r[:6]) for r in rows):
            kind_l, url = str(kind).lower(), str(url).strip()
            if any(k in kind_l for k in SKIP_TYPES):
                skipped.append((name, kind))
                continue
            if args.team and plain(str(team)) != plain(args.team):
                continue
            code = teams.get(plain(str(team)), "")
            if not code and str(team).lower() != "league-wide":
                failed.append((name, f"unknown team {team!r}"))
                continue
            audience = "media" if any(k in kind_l for k in MEDIA_TYPES) else "fan"
            if "youtube" in kind_l:
                value = youtube_value(url)
                feed_kind = "youtube_channel"
                if not value:
                    failed.append((name, "YouTube link without an @handle or channel id"))
                    continue
            else:
                value = discover_feed(http, url)
                feed_kind = "rss"
                if not value:
                    failed.append((name, f"no working feed found at {url}"))
                    continue
            if (feed_kind, value.lower().rstrip("/")) in have:
                skipped.append((name, "already in feeds.csv"))
                continue
            have.add((feed_kind, value.lower().rstrip("/")))
            row = {"kind": feed_kind, "value": value, "team": code, "audience": audience,
                   "label": f"{name}"[:80], "active": "yes", "notes": f"{kind} from Brian's fan sources list"}
            writer.writerow(row)   # saved as found, so an interrupted run keeps its progress
            out.flush()
            added.append(row)
            print(f"  + {feed_kind:15} {code or 'NHL':4} {name}", flush=True)

    out.close()
    print(f"\nAdded {len(added)} feeds; skipped {len(skipped)} (X, Reddit, forums, or already listed); "
          f"{len(failed)} could not be added:")
    for name, why in failed:
        print(f"  - {name}: {why}")


if __name__ == "__main__":
    sys.exit(main())
