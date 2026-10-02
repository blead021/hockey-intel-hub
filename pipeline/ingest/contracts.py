"""Loads player contracts from a manually maintained CSV (data/contracts.csv).

Usage: python -m pipeline.ingest.contracts [path/to/contracts.csv]

The CSV is the source of truth: each load replaces the contracts table with its rows. Refresh it
weekly and after trades from PuckPedia or CapWages. If a licensed contracts API is obtained later,
only this loader changes.

Columns: player, team, cap_hit, aav, start_season, end_season, expiry_status, clause,
no_trade_list_size, retained_pct, retained_by
- Money accepts 8000000, 8,000,000, or $8,000,000. Seasons accept 20252026 or 2025-26.
- expiry_status: UFA or RFA. clause: NMC, NTC, M-NTC, or none. team and retained_by: codes like VAN.
"""

import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from pipeline.config import REPO_ROOT
from pipeline.db import connect
from pipeline.jobs import job_run
from pipeline.sources import require_enabled

CSV_PATH = REPO_ROOT / "data" / "contracts.csv"
COLUMNS = [
    "player", "team", "cap_hit", "aav", "start_season", "end_season", "expiry_status", "clause",
    "no_trade_list_size", "retained_pct", "retained_by",
]
CLAUSES = {"NMC", "NTC", "M-NTC", "NONE"}


@dataclass(frozen=True)
class ContractRow:
    line: int
    player: str
    team: str | None
    cap_hit: int
    aav: int | None
    start_season: int
    end_season: int
    expiry_status: str | None
    clause: str
    no_trade_list_size: int | None
    retained_pct: float
    retained_by: str | None


def parse_money(value: str) -> int | None:
    cleaned = re.sub(r"[$,\s]", "", value or "")
    if not cleaned:
        return None
    if not cleaned.isdigit():
        raise ValueError(f"not a dollar amount: {value!r}")
    return int(cleaned)


def parse_season(value: str) -> int:
    """20252026 or 2025-26 (also 2025-2026) -> 20252026."""
    value = (value or "").strip()
    if re.fullmatch(r"\d{8}", value):
        start, end = int(value[:4]), int(value[4:])
    else:
        match = re.fullmatch(r"(\d{4})-(\d{2}|\d{4})", value)
        if not match:
            raise ValueError(f"not a season: {value!r} (use 2025-26 or 20252026)")
        start, tail = int(match.group(1)), match.group(2)
        if len(tail) == 4:
            end = int(tail)
        else:
            end = start + 1 if int(tail) == (start + 1) % 100 else -1  # "2099-00" is 2099-2100
    if end != start + 1:
        raise ValueError(f"not a season: {value!r}")
    return start * 10000 + end


def read_csv(path: Path = CSV_PATH) -> list[ContractRow]:
    rows, errors = [], []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if [c.strip() for c in reader.fieldnames or []] != COLUMNS:
            raise ValueError(f"{path.name}: columns must be exactly {', '.join(COLUMNS)}")
        for line, rec in enumerate(reader, start=2):
            rec = {k.strip(): (v or "").strip() for k, v in rec.items()}
            try:
                cap_hit = parse_money(rec["cap_hit"])
                if cap_hit is None:
                    raise ValueError("cap_hit is empty")
                clause = (rec["clause"] or "none").upper()
                if clause not in CLAUSES:
                    raise ValueError(f"clause must be NMC, NTC, M-NTC, or none, not {rec['clause']!r}")
                expiry = rec["expiry_status"].upper() or None
                if expiry not in (None, "UFA", "RFA"):
                    raise ValueError(f"expiry_status must be UFA or RFA, not {rec['expiry_status']!r}")
                start, end = parse_season(rec["start_season"]), parse_season(rec["end_season"])
                if end < start:
                    raise ValueError("end_season is before start_season")
                rows.append(
                    ContractRow(
                        line=line,
                        player=rec["player"],
                        team=rec["team"].upper() or None,
                        cap_hit=cap_hit,
                        aav=parse_money(rec["aav"]),
                        start_season=start,
                        end_season=end,
                        expiry_status=expiry,
                        clause="none" if clause == "NONE" else clause,
                        no_trade_list_size=int(rec["no_trade_list_size"]) if rec["no_trade_list_size"] else None,
                        retained_pct=float(rec["retained_pct"].rstrip("%")) if rec["retained_pct"] else 0.0,
                        retained_by=rec["retained_by"].upper() or None,
                    )
                )
                if not rec["player"]:
                    raise ValueError("player is empty")
            except ValueError as exc:
                errors.append(f"line {line}: {exc}")
    if errors:
        raise ValueError(f"{path.name} has problems:\n  " + "\n  ".join(errors))
    return rows


def match_players(conn, rows: list[ContractRow]) -> dict[int, int | None]:
    """Finds each contract's player by name, using the team to separate players who share a name."""
    matches = {}
    for r in rows:
        candidates = conn.execute(
            """select distinct p.id, t.abbrev from player_aliases a
               join players p on p.id = a.player_id left join teams t on t.id = p.current_team_id
               where lower(a.alias) = lower(%s)""",
            (r.player,),
        ).fetchall()
        if len(candidates) > 1 and r.team:
            candidates = [c for c in candidates if c[1] == r.team]
        matches[r.line] = candidates[0][0] if len(candidates) == 1 else None
    return matches


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    path = Path(argv[0]) if argv else CSV_PATH
    rows = read_csv(path)
    with job_run("contracts") as counts, connect() as conn:
        require_enabled(conn, "contracts_csv")
        teams = dict(conn.execute("select abbrev, id from teams where active").fetchall())
        unknown = sorted({c for r in rows for c in (r.team, r.retained_by) if c and c not in teams})
        if unknown:
            raise ValueError(f"Unknown team codes in {path.name}: {', '.join(unknown)}")
        matches = match_players(conn, rows)
        with conn.transaction():
            conn.execute("delete from contracts")
            with conn.cursor() as cur:
                cur.executemany(
                    """insert into contracts (player_id, player_name, team_id, cap_hit, aav, start_season,
                           end_season, expiry_status, clause, no_trade_list_size, retained_pct, retained_by)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    [
                        (matches[r.line], r.player, teams.get(r.team), r.cap_hit, r.aav, r.start_season,
                         r.end_season, r.expiry_status, r.clause, r.no_trade_list_size, r.retained_pct,
                         teams.get(r.retained_by))
                        for r in rows
                    ],
                )
        counts["contracts"] = len(rows)
        unmatched = [r for r in rows if matches[r.line] is None]
        counts["unmatched"] = len(unmatched)
    for r in unmatched:
        print(f"line {r.line}: no single player found for {r.player!r} ({r.team or 'no team'}); check the spelling")
    print(f"contracts ok: {dict(counts)}")


if __name__ == "__main__":
    main()
