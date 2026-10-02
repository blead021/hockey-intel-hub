"""Loads the starting contracts data from contracts_template.xlsx (or a CSV with the same columns).

Usage:
    python -m pipeline.ingest.contracts                        contracts_template.xlsx at the repo root
    python -m pipeline.ingest.contracts path/to/file.csv       a CSV instead
    python -m pipeline.ingest.contracts --replace              replace contracts already updated from news

This is a one-time starting point. After it, the daily contract news job (pipeline.contracts.update)
keeps contracts current, so loading again would erase its updates unless --replace is given.

Every row with a player and a team code is loaded. A missing or unreadable detail is stored as
unknown, and every such row is listed so it can be fixed in the file. Rows without a player or a
valid team code cannot be stored and are listed too.
Required: player, team, cap_hit, start_season, end_season. Other columns may be blank or "unknown".
- Money accepts 8000000, 8,000,000, or $8,000,000. Seasons accept 20252026, 2025-26, or 2025-2026.
- expiry_status: UFA or RFA. clause: NMC, NTC, M-NTC, or none. team and retained_by: codes like VAN.
- retained_pct: blank means 0 (no salary retained).
"""

import argparse
import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.config import REPO_ROOT
from pipeline.db import connect
from pipeline.jobs import job_run
from pipeline.sources import require_enabled

XLSX_PATH = REPO_ROOT / "contracts_template.xlsx"
CSV_PATH = REPO_ROOT / "data" / "contracts.csv"
COLUMNS = [
    "player", "team", "cap_hit", "aav", "start_season", "end_season", "expiry_status", "clause",
    "no_trade_list_size", "retained_pct", "retained_by",
]
REQUIRED = ("player", "team", "cap_hit", "start_season", "end_season")
CLAUSES = {"NMC": "NMC", "NTC": "NTC", "M-NTC": "M-NTC", "NONE": "none"}
UNKNOWN = {"", "UNKNOWN", "?", "N/A", "NA", "TBD"}


@dataclass(frozen=True)
class ContractRow:
    line: int
    player: str
    team: str
    cap_hit: int | None
    aav: int | None
    start_season: int | None
    end_season: int | None
    expiry_status: str | None
    clause: str | None
    no_trade_list_size: int | None
    retained_pct: float
    retained_by: str | None


@dataclass
class ReadResult:
    rows: list[ContractRow] = field(default_factory=list)
    problems: list[tuple[int, str, str]] = field(default_factory=list)  # (line, player, problem)


def is_unknown(value) -> bool:
    return str(value if value is not None else "").strip().upper() in UNKNOWN


def parse_money(value) -> int | None:
    if is_unknown(value):
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    cleaned = re.sub(r"[$,\s]", "", str(value))
    if re.fullmatch(r"\d+(\.\d+)?[mM]", cleaned):  # "7.85M"
        return int(round(float(cleaned[:-1]) * 1_000_000))
    if not re.fullmatch(r"\d+(\.\d+)?", cleaned):
        raise ValueError(f"not a dollar amount: {value!r}")
    return int(round(float(cleaned)))


def parse_season(value) -> int | None:
    """20252026, 2025-26, or 2025-2026 -> 20252026."""
    if is_unknown(value):
        return None
    value = str(value).strip()
    if re.fullmatch(r"\d{8}", value):
        start, end = int(value[:4]), int(value[4:])
    else:
        match = re.fullmatch(r"(\d{4})-(\d{2}|\d{4})", value)
        if not match:
            raise ValueError(f"not a season: {value!r} (use 2025-26)")
        start, tail = int(match.group(1)), match.group(2)
        if len(tail) == 4:
            end = int(tail)
        else:
            end = start + 1 if int(tail) == (start + 1) % 100 else -1  # "2099-00" is 2099-2100
    if end != start + 1:
        raise ValueError(f"not a season: {value!r}")
    return start * 10000 + end


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def parse_record(line: int, rec: dict) -> tuple[ContractRow | None, list[str]]:
    """Turns one spreadsheet row into a ContractRow plus its problems. Unreadable details become None
    (unknown). Returns no row when there is no player or team to attach it to."""
    errors = []
    for name in REQUIRED:
        if is_unknown(rec.get(name)):
            errors.append(f"{name} is missing")

    def attempt(fn, *args):
        try:
            return fn(*args)
        except ValueError as exc:
            errors.append(str(exc))
            return None

    cap_hit = attempt(parse_money, rec.get("cap_hit"))
    aav = attempt(parse_money, rec.get("aav"))
    start = attempt(parse_season, rec.get("start_season"))
    end = attempt(parse_season, rec.get("end_season"))
    if start and end and end < start:
        errors.append("end_season is before start_season")

    expiry = _text(rec.get("expiry_status")).upper()
    expiry = None if is_unknown(expiry) else expiry
    if expiry not in (None, "UFA", "RFA"):
        errors.append(f"expiry_status must be UFA or RFA, not {expiry!r}")

    clause_raw = _text(rec.get("clause")).upper()
    clause = None if is_unknown(clause_raw) else CLAUSES.get(clause_raw)
    if clause_raw and not is_unknown(clause_raw) and clause is None:
        errors.append(f"clause must be NMC, NTC, M-NTC, or none, not {rec.get('clause')!r}")

    ntc = _text(rec.get("no_trade_list_size"))
    ntc_size = None
    if not is_unknown(ntc):
        if re.fullmatch(r"\d+(\.0)?", ntc):
            ntc_size = int(float(ntc))
        else:
            errors.append(f"no_trade_list_size must be a whole number, not {ntc!r}")

    retained_raw = _text(rec.get("retained_pct")).rstrip("%")
    retained: float | None = 0.0
    if retained_raw and not is_unknown(retained_raw):
        try:
            retained = float(retained_raw)
            if retained <= 1 and retained > 0 and "." in retained_raw:  # 0.5 written as a fraction
                retained *= 100
            if not 0 <= retained <= 50:
                errors.append(f"retained_pct must be between 0 and 50, not {retained_raw}")
                retained = None
        except ValueError:
            errors.append(f"retained_pct is not a number: {retained_raw!r}")
            retained = None

    if is_unknown(rec.get("player")) or is_unknown(rec.get("team")):
        return None, errors
    return ContractRow(
        line=line,
        player=_text(rec["player"]),
        team=_text(rec["team"]).upper(),
        cap_hit=cap_hit,
        aav=aav,
        start_season=start,
        end_season=end,
        expiry_status=expiry,
        clause=clause,
        no_trade_list_size=ntc_size,
        retained_pct=retained,
        retained_by=None if is_unknown(rec.get("retained_by")) else _text(rec.get("retained_by")).upper(),
    ), errors


def _records(path: Path):
    """Yields (line number, {column: value}) from an .xlsx (sheet "contracts") or a .csv."""
    if path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        named = [name for name in wb.sheetnames if name.strip().lower() == "contracts"]
        ws = wb[named[0]] if named else wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        header = [_text(h).lower() for h in next(rows, [])]
        _check_header(header, path)
        for line, values in enumerate(rows, start=2):
            if values is None or all(v is None or _text(v) == "" for v in values):
                continue
            yield line, dict(zip(header, values))
    else:
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            _check_header([h.strip().lower() for h in reader.fieldnames or []], path)
            for line, rec in enumerate(reader, start=2):
                if all(not (v or "").strip() for v in rec.values()):
                    continue
                yield line, {k.strip().lower(): v for k, v in rec.items()}


def _check_header(header: list[str], path: Path) -> None:
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        raise ValueError(f"{path.name}: missing columns {', '.join(missing)}")


def read_file(path: Path) -> ReadResult:
    result = ReadResult()
    for line, rec in _records(path):
        row, errors = parse_record(line, rec)
        name = _text(rec.get("player")) or "(no name)"
        if row is None:
            errors.append("not loaded: a row needs a player and a team")
        else:
            result.rows.append(row)
        if errors:
            result.problems.append((line, name, "; ".join(errors)))
    return result


def read_csv(path: Path = CSV_PATH) -> list[ContractRow]:
    """Strict reader kept for tests and CSV users: raises on the first file with any bad row."""
    result = read_file(path)
    if result.problems:
        raise ValueError(f"{path.name} has problems:\n  " + "\n  ".join(f"line {l}: {p}" for l, _, p in result.problems))
    return result.rows


def normalize(name: str) -> str:
    """Lowercase, no accents or punctuation: "J.T Compher" and "Söderblom" compare as "jt compher", "soderblom"."""
    decomposed = unicodedata.normalize("NFKD", name)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[.'’]", "", plain).replace("-", " ")).strip().lower()


def match_players(conn, rows: list[ContractRow]) -> dict[int, int | None]:
    """Finds each contract's player.

    1. The name as written (any alias), using the team to separate players who share a name.
    2. Otherwise the same surname on the same current team, if exactly one player fits. This covers
       formal first names (Zachary for Zach), accents, punctuation, and double surnames.
    3. Two players with the same name on the same team (the two Elias Petterssons): an RFA contract goes
       to the younger player and a UFA contract to the older one, since RFA status depends on age.
    """
    roster = conn.execute(
        """select p.id, p.first_name, p.last_name, t.abbrev, p.birth_date
           from players p join teams t on t.id = coalesce(p.current_team_id, p.rights_team_id)"""
    ).fetchall()
    born = {pid: birth for pid, _, _, _, birth in roster}
    by_full: dict[str, list] = {}
    for pid, first, last, team, _ in roster:
        by_full.setdefault(normalize(f"{first} {last}"), []).append((pid, team))
    # Everyone we know, including depth players with no current NHL team or prospect listing.
    anyone: dict[str, list] = {}
    for pid, first, last in conn.execute("select id, first_name, last_name from players").fetchall():
        anyone.setdefault(normalize(f"{first} {last}"), []).append((pid, None))
    matches = {}
    for r in rows:
        candidates = conn.execute(
            """select distinct p.id, t.abbrev from player_aliases a
               join players p on p.id = a.player_id left join teams t on t.id = p.current_team_id
               where lower(a.alias) = lower(%s)""",
            (r.player,),
        ).fetchall()
        if not candidates:
            candidates = by_full.get(normalize(r.player), [])
        if len(candidates) > 1:
            candidates = [c for c in candidates if c[1] == r.team]
        if len(candidates) > 1 and r.expiry_status in ("RFA", "UFA") and all(born.get(c[0]) for c in candidates):
            ordered = sorted(candidates, key=lambda c: born[c[0]])   # oldest first
            candidates = [ordered[-1] if r.expiry_status == "RFA" else ordered[0]]
        if len(candidates) != 1:
            wanted = normalize(r.player).split(" ")
            surname_fits = [
                (pid, team) for pid, first, last, team, _ in roster
                if team == r.team and normalize(last).split(" ")[-1] in wanted[1:]
            ]
            candidates = surname_fits if len(surname_fits) == 1 else []
        if not candidates:
            # 4. A name that belongs to exactly one player we know, on any team.
            candidates = anyone.get(normalize(r.player), [])
        matches[r.line] = candidates[0][0] if len(candidates) == 1 else None
    return matches


PLAYER_SEARCH = "https://search.d3.nhle.com/api/v1/search/player"


def lookup_unmatched(conn, http, rows: list[ContractRow], matches: dict[int, int | None], teams: dict[str, int], counts) -> None:
    """Players under contract who never played an NHL game (and are not on a prospect list) are not in our
    players table yet. Find each by exact name in the NHL's player search, preferring the contract's team,
    add him with his NHL profile, and record the contract team as holding his rights."""
    from pipeline.http import get_json
    from pipeline.ingest import nhl
    from pipeline.ingest.nhl_players import upsert_players

    for r in rows:
        if matches[r.line] is not None:
            continue
        results = get_json(http, PLAYER_SEARCH, params={"culture": "en-us", "limit": 20, "q": r.player})
        same_name = [x for x in results if normalize(x.get("name") or "") == normalize(r.player)]
        on_team = [x for x in same_name if r.team in (x.get("teamAbbrev"), x.get("lastTeamAbbrev"))]
        found = on_team if len(on_team) == 1 else same_name if len(same_name) == 1 else []
        if not found:
            # Formal first names (Michael for Mike, Zachary for Zac): same surname, same team, same first initial.
            first, last = normalize(r.player).split(" ", 1)[0], normalize(r.player).split(" ")[-1]
            by_surname = get_json(http, PLAYER_SEARCH, params={"culture": "en-us", "limit": 40, "q": last})
            found = [
                x for x in by_surname
                if normalize(x.get("name") or "").split(" ")[-1] == last
                and normalize(x.get("name") or "")[:1] == first[:1]
                and r.team in (x.get("teamAbbrev"), x.get("lastTeamAbbrev"))
            ]
            if len(found) != 1:
                continue
        player_id = int(found[0]["playerId"])
        info = nhl.parse_landing(nhl.player_landing(http, player_id))
        with conn.transaction():
            upsert_players(conn, [info])
            conn.execute(
                "update players set rights_team_id = %s where id = %s and current_team_id is null",
                (teams[r.team], player_id),
            )
        matches[r.line] = player_id
        counts["players_added_from_search"] += 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load the starting contracts data")
    parser.add_argument("path", nargs="?", type=Path, default=XLSX_PATH if XLSX_PATH.exists() else CSV_PATH)
    parser.add_argument("--replace", action="store_true", help="replace contracts already updated from news")
    args = parser.parse_args(argv)

    result = read_file(args.path)
    with job_run("contracts_import") as counts, connect() as conn:
        require_enabled(conn, "contracts_csv")
        news_updates = conn.execute("select count(*) from contract_changes").fetchone()[0]
        if news_updates and not args.replace:
            raise RuntimeError(
                f"{news_updates} contract changes have been made from news since the first load. "
                "Loading the file again would erase them; rerun with --replace only if that is intended."
            )
        teams = dict(conn.execute("select abbrev, id from teams where active").fetchall())
        good = []
        for r in result.rows:
            if r.team not in teams:
                result.problems.append((r.line, r.player, f"not loaded: unknown team code {r.team}"))
                continue
            if r.retained_by and r.retained_by not in teams:
                result.problems.append((r.line, r.player, f"unknown retained_by code {r.retained_by}; stored as unknown"))
                r = ContractRow(**{**r.__dict__, "retained_by": None})
            good.append(r)
        matches = match_players(conn, good)
        from pipeline.http import client
        with client() as http:
            lookup_unmatched(conn, http, good, matches, teams, counts)
        # One contract per player per start season. Keep the row for the player's current NHL team
        # (otherwise the first row) and report the rest.
        current_team = dict(conn.execute(
            "select p.id, t.abbrev from players p join teams t on t.id = p.current_team_id").fetchall())
        kept: dict[tuple, ContractRow] = {}
        for r in good:
            who = matches[r.line] or r.player.lower()
            # The same player with the same end season and cap hit is the same contract, even if one row
            # lacks the start season (a traded player listed under both teams).
            key = (who, "end", r.end_season, r.cap_hit) if r.end_season is not None else (who, r.start_season, r.line)
            if key not in kept:
                kept[key] = r
                continue
            first = kept[key]
            pid = matches[r.line]
            if pid and current_team.get(pid) == r.team and current_team.get(pid) != first.team:
                kept[key], r, first = r, first, r
            # Keep details only the dropped row has (start season, clause, and so on); the kept row's team stays.
            merged = {k: (v if v is not None else getattr(r, k)) for k, v in first.__dict__.items()}
            kept[key] = first = ContractRow(**merged)
            result.problems.append((r.line, r.player,
                                    f"duplicate of row {first.line} (same player and contract); kept row {first.line} "
                                    f"({first.team}), this row not loaded"))
        good = sorted(kept.values(), key=lambda r: r.line)
        unmatched = [r for r in good if matches[r.line] is None]
        for r in unmatched:
            result.problems.append((r.line, r.player, f"no single NHL player named {r.player!r} on {r.team}; loaded without a player link"))

        with conn.transaction():
            conn.execute("delete from contracts")
            with conn.cursor() as cur:
                cur.executemany(
                    """insert into contracts (player_id, player_name, team_id, cap_hit, aav, start_season,
                           end_season, expiry_status, clause, no_trade_list_size, retained_pct, retained_by,
                           status, source)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', 'starting_file')""",
                    [
                        (matches[r.line], r.player, teams[r.team], r.cap_hit, r.aav, r.start_season,
                         r.end_season, r.expiry_status, r.clause, r.no_trade_list_size, r.retained_pct,
                         teams.get(r.retained_by))
                        for r in good
                    ],
                )
        counts["rows_loaded"] = len(good)
        counts["rows_with_problems"] = len({line for line, _, _ in result.problems})
        counts["unmatched_players"] = len(unmatched)

    print(f"Loaded {len(good)} contracts from {args.path.name}.")
    if result.problems:
        print(f"\n{len(result.problems)} problems (row numbers match the spreadsheet):")
        # One line for the many rows that only lack a start season (stored as unknown).
        no_start = [p for p in result.problems if p[2] == "start_season is missing"]
        if no_start:
            print(f"  {len(no_start)} rows have no start_season; loaded with it unknown "
                  f"(rows {', '.join(str(p[0]) for p in sorted(no_start)[:8])}, ...)")
        for line, player, problem in sorted(p for p in result.problems if p not in no_start):
            print(f"  row {line}  {player}: {problem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
