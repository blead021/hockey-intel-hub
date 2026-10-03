"""Finds news of NHL contract transactions: official team announcements and news coverage.

Reads Google News search results (headline, outlet, date, link) only. It never opens contract
database sites (PuckPedia, Spotrac, CapWages, and the like) and never downloads full articles.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import feedparser

from pipeline import archive
from pipeline.http import request
from pipeline.sentiment.models import strip_html
from pipeline.sentiment.rss import GOOGLE_NEWS_URL, news_key

# NHL.com hosts every team's press releases and the league's transaction stories.
QUERIES = [
    'site:nhl.com (signs OR "contract extension" OR "entry-level contract" OR "agree to terms" OR "re-sign")',
    "site:nhl.com (acquire OR acquires OR traded OR trade OR retain OR retained)",
    'site:nhl.com (waivers OR claimed OR claim OR buyout OR "buy out" OR "bought out" OR terminate OR "mutual termination")',
    'NHL (signs OR extension OR "entry-level") contract "cap hit"',
    'NHL trade "retained" OR "retain" salary',
    'NHL ("claimed off waivers" OR "buyout" OR "bought out" OR "contract terminated")',
    'site:nhl.com (recalled OR recalls OR assigned OR assigns OR reassigned OR "injured reserve" OR LTIR OR activated)',
    'NHL ("assigned to" OR "recalled from" OR "sent down" OR "placed on injured reserve" OR "long-term injured reserve")',
]
LOOKBACK = "when:2d"
BLOCKED_OUTLETS = re.compile(r"puckpedia|spotrac|capwages|capfriendly|cap ?friendly", re.IGNORECASE)
TRANSACTION_WORDS = re.compile(
    r"\b(sign|signs|signed|signing|re-sign|extension|extend|extends|contract|deal|agree|terms|entry-level|"
    r"elc|acquire|acquires|acquired|trade|trades|traded|retain|retained|waiver|waivers|claim|claims|claimed|"
    r"buyout|buy out|bought out|terminate|terminated|termination|tender|one-year|two-year|three-year|"
    r"four-year|five-year|six-year|seven-year|eight-year|roster moves?|transactions?|recall|recalls|recalled|"
    r"assign|assigns|assigned|reassigned|loaned|sent down|injured reserve|ltir|activated|activate|call(?:ed)? up)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NewsItem:
    id: str
    title: str
    outlet: str | None
    url: str | None
    published_at: datetime | None
    query: str


def parse_results(content: bytes, query: str) -> list[NewsItem]:
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"could not read news results for {query!r}: {parsed.bozo_exception}")
    items = []
    for entry in parsed.entries:
        title = strip_html(entry.get("title"))
        outlet = (entry.get("source") or {}).get("title")
        if outlet and title.endswith(f" - {outlet}"):
            title = title[: -len(f" - {outlet}")]
        when = entry.get("published_parsed")
        items.append(
            NewsItem(
                id=news_key(title, outlet),
                title=title,
                outlet=outlet,
                url=entry.get("link"),
                published_at=datetime.fromtimestamp(calendar.timegm(when), UTC) if when else None,
                query=query,
            )
        )
    return items


def is_candidate(item: NewsItem) -> bool:
    """Cheap filter before paying for Claude: transaction words, and never a contract database site."""
    if BLOCKED_OUTLETS.search(item.outlet or "") or BLOCKED_OUTLETS.search(item.url or ""):
        return False
    return bool(TRANSACTION_WORDS.search(item.title))


def collect(conn, http, counts) -> None:
    """Saves new news items. Ones that are clearly not transactions are marked skipped right away."""
    seen: dict[str, NewsItem] = {}
    for query in QUERIES:
        params = {"q": f"{query} {LOOKBACK}", "hl": "en-US", "gl": "US", "ceid": "US:en"}
        response = request(http, "GET", GOOGLE_NEWS_URL, params=params)
        archive.save("contract_news", query[:60], {"query": query, "xml": response.text})
        for item in parse_results(response.content, query):
            seen.setdefault(item.id, item)
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            """insert into contract_news (id, title, outlet, url, published_at, query, status, processed_at, error)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s) on conflict (id) do nothing""",
            [
                (i.id, i.title, i.outlet, i.url, i.published_at, i.query,
                 "pending" if is_candidate(i) else "skipped",
                 None if is_candidate(i) else datetime.now(UTC),
                 None if is_candidate(i) else "not a transaction headline")
                for i in seen.values()
            ],
        )
        counts["news_new"] += cur.rowcount
    counts["news_seen"] += len(seen)
