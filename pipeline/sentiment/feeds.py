"""Loads pipeline/sentiment/feeds.csv into the sentiment_feeds table.

The CSV is the list of everything the collectors watch. Edit it (Excel works), then run:
    python -m pipeline.sentiment.feeds

Rows removed from the CSV are switched off, not deleted, so their history stays linked.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from pipeline.db import connect

CSV_PATH = Path(__file__).with_name("feeds.csv")
KINDS = {"subreddit", "bluesky_account", "bluesky_search", "rss", "google_news", "youtube_channel"}
AUDIENCES = {"fan", "beat_writer", "media"}
COLUMNS = ["kind", "value", "team", "audience", "label", "active", "notes"]


@dataclass(frozen=True)
class FeedRow:
    kind: str
    value: str
    team: str | None
    audience: str
    label: str | None
    active: bool
    notes: str | None


def read_csv(path: Path = CSV_PATH) -> list[FeedRow]:
    """Reads and checks the CSV, reporting every bad line at once."""
    rows, errors, seen = [], [], set()
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"{path.name}: columns must be exactly {', '.join(COLUMNS)}")
        for line, rec in enumerate(reader, start=2):
            kind, value = rec["kind"].strip(), rec["value"].strip()
            audience = rec["audience"].strip()
            if kind not in KINDS:
                errors.append(f"line {line}: unknown kind {kind!r}")
            if not value:
                errors.append(f"line {line}: value is empty")
            if audience not in AUDIENCES:
                errors.append(f"line {line}: audience must be fan, beat_writer, or media")
            if kind == "bluesky_account":
                value = value.lstrip("@").lower()
            if (kind, value.lower()) in seen:
                errors.append(f"line {line}: duplicate {kind} {value!r}")
            seen.add((kind, value.lower()))
            rows.append(
                FeedRow(
                    kind=kind,
                    value=value,
                    team=rec["team"].strip().upper() or None,
                    audience=audience,
                    label=rec["label"].strip() or None,
                    active=rec["active"].strip().lower() not in {"no", "false", "0", "n"},
                    notes=rec["notes"].strip() or None,
                )
            )
    if errors:
        raise ValueError(f"{path.name} has problems:\n  " + "\n  ".join(errors))
    return rows


def sync(conn, rows: list[FeedRow]) -> dict:
    teams = dict(conn.execute("select abbrev, id from teams").fetchall())
    unknown = sorted({r.team for r in rows if r.team and r.team not in teams})
    if unknown:
        raise ValueError(
            f"Unknown team codes in feeds.csv: {', '.join(unknown)}. "
            "Run `python -m pipeline.ingest.nhl_teams` first if the teams table is empty."
        )
    with conn.transaction():
        ids = []
        for r in rows:
            ids.append(
                conn.execute(
                    """insert into sentiment_feeds (kind, value, team_id, audience, label, active, notes)
                       values (%s, %s, %s, %s, %s, %s, %s)
                       on conflict (kind, value) do update set team_id = excluded.team_id,
                         audience = excluded.audience, label = excluded.label, active = excluded.active,
                         notes = excluded.notes, updated_at = now()
                       returning id""",
                    (r.kind, r.value, teams.get(r.team), r.audience, r.label, r.active, r.notes),
                ).fetchone()[0]
            )
        removed = conn.execute(
            "update sentiment_feeds set active = false, updated_at = now() where active and id <> all(%s)",
            (ids,),
        ).rowcount
    return {"feeds": len(rows), "active": sum(r.active for r in rows), "switched_off": removed}


def main() -> None:
    rows = read_csv()
    with connect() as conn:
        print(f"feeds synced: {sync(conn, rows)}")


if __name__ == "__main__":
    main()
