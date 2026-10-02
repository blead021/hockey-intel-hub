"""Applies extracted transactions to the contracts table, and logs every field it changes.

Rules (CLAUDE.md, Contracts):
- Only completed transactions change anything. Reported deals and rumors are logged and skipped.
- A detail the news does not mention keeps the value already on file.
- A new contract stores unmentioned details as unknown (NULL). Nothing is guessed.
- The only derived values are plain arithmetic on stated facts, and the log says so:
  cap hit = total value / years (an NHL cap hit is the contract's average annual value), the
  missing end of a season range from the other end and the length, and an extension's first
  season as the season after the current contract on file ends.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal

from psycopg.types.json import Jsonb

from pipeline.ingest.nightly import current_season

CONTRACT_TYPES = {"signing": "standard", "extension": "extension", "entry_level": "entry_level"}
TEAM_MOVES = {"trade", "waiver_claim"}
ENDINGS = {"buyout": "bought_out", "termination": "terminated"}
TRACKED = [
    "team_id", "cap_hit", "aav", "start_season", "end_season", "expiry_status", "clause",
    "no_trade_list_size", "retained_pct", "retained_by", "status", "contract_type",
]


def season_id(value: str | None) -> int | None:
    """ "2027-28" -> 20272028. Anything unreadable is unknown."""
    if not value:
        return None
    match = re.fullmatch(r"(\d{4})-(\d{2}|\d{4})", value.strip())
    if not match:
        return None
    start = int(match.group(1))
    tail = match.group(2)
    end = int(tail) if len(tail) == 4 else (start + 1 if int(tail) == (start + 1) % 100 else -1)
    return start * 10000 + end if end == start + 1 else None


def shift(season: int, years: int) -> int:
    start = season // 10000 + years
    return start * 10000 + start + 1


@dataclass
class Plan:
    """What one transaction would do: field values for a new or existing contract, plus notes."""
    values: dict = field(default_factory=dict)
    derived: list[str] = field(default_factory=list)


def plan_contract_terms(t: dict, current_end: int | None) -> Plan:
    """Turns stated terms into contract fields, deriving only by arithmetic on stated facts."""
    plan = Plan()
    start, end, years = season_id(t.get("start_season")), season_id(t.get("end_season")), t.get("years")
    if start is None and t["type"] == "extension" and current_end:
        start = shift(current_end, 1)
        plan.derived.append("start season: the season after the current contract on file ends")
    if start is None and end and years:
        start = shift(end, -(years - 1))
        plan.derived.append("start season: from end season and length")
    if end is None and start and years:
        end = shift(start, years - 1)
        plan.derived.append("end season: from start season and length")

    cap_hit = t.get("cap_hit")
    aav = None
    if t.get("total_value") and years:
        aav = round(t["total_value"] / years)
        if cap_hit is None:
            cap_hit = aav
            plan.derived.append("cap hit: total value divided by years")

    for key, value in (
        ("cap_hit", cap_hit), ("aav", aav), ("start_season", start), ("end_season", end),
        ("expiry_status", t.get("expiry_status")), ("clause", t.get("clause")),
        ("no_trade_list_size", t.get("no_trade_list_size")),
    ):
        if value is not None:
            plan.values[key] = value
    plan.values["contract_type"] = CONTRACT_TYPES[t["type"]]
    return plan


def match_player(conn, name: str, team_codes: list[str]) -> int | None:
    rows = conn.execute(
        """select distinct p.id, t.abbrev from player_aliases a join players p on p.id = a.player_id
           left join teams t on t.id = p.current_team_id where lower(a.alias) = lower(%s)""",
        (name.strip(),),
    ).fetchall()
    if len(rows) > 1:
        rows = [r for r in rows if r[1] in team_codes] or rows
    return rows[0][0] if len(rows) == 1 else None


def same_value(old, new) -> bool:
    """Numbers compare by value (the database returns 50.00 where the news says 50)."""
    if isinstance(old, (int, float, Decimal)) and isinstance(new, (int, float, Decimal)):
        return float(old) == float(new)
    return old == new


def _as_text(value) -> str | None:
    return None if value is None else str(value)


class Applier:
    def __init__(self, conn, run_id: int | None, model: str, teams: dict[str, int]):
        self.conn, self.run_id, self.model, self.teams = conn, run_id, model, teams

    def apply(self, t: dict, news: list[dict]) -> str:
        """Applies one transaction inside a transaction block. Returns its outcome."""
        urls = [n["url"] for n in news if n.get("url")]
        player_id = match_player(self.conn, t["player_name"], [c for c in (t.get("team"), t.get("from_team")) if c])
        team_id = self.teams.get((t.get("team") or "").upper())

        with self.conn.transaction():
            outcome, note, changes = self._decide(t, player_id, team_id)
            event_id = self.conn.execute(
                """insert into contract_events (job_run_id, event_type, event_status, player_name, player_id,
                       details, news_ids, source_urls, outcome, outcome_note, model)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                (self.run_id, t["type"], t["status"], t["player_name"], player_id, Jsonb(t),
                 [n["id"] for n in news], urls, outcome, note, self.model),
            ).fetchone()[0]
            for contract_id, action, fld, old, new in changes:
                self.conn.execute(
                    """insert into contract_changes (event_id, contract_id, player_id, action, field,
                           old_value, new_value, source_urls)
                       values (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (event_id, contract_id, player_id, action, fld, _as_text(old), _as_text(new), urls),
                )
        return outcome

    def _decide(self, t: dict, player_id: int | None, team_id: int | None):
        if t["status"] != "completed":
            return "skipped_unconfirmed", f"news says {t['status']}, not completed", []
        if t["type"] in CONTRACT_TYPES:
            if team_id is None:
                return "skipped_unmatched", f"unknown team {t.get('team')!r}", []
            return self._sign(t, player_id, team_id)
        if player_id is None:
            return "skipped_unmatched", f"no single NHL player named {t['player_name']!r}", []
        if t["type"] in TEAM_MOVES:
            if team_id is None:
                return "skipped_unmatched", f"unknown team {t.get('team')!r}", []
            return self._move(t, player_id, team_id)
        if t["type"] in ENDINGS:
            return self._end(t, player_id)
        return "skipped_type", f"{t['type']} does not change a contract", []

    def _current(self, player_id: int) -> list[dict]:
        """Active contracts that are not over yet (or whose end is unknown), latest first."""
        season = current_season()
        cur = self.conn.execute(
            f"""select id, {", ".join(TRACKED)} from contracts
                where player_id = %s and status = 'active' and (end_season is null or end_season >= %s)
                order by start_season desc nulls last""",
            (player_id, season),
        )
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def _update(self, contract: dict, values: dict) -> list:
        changed = {k: v for k, v in values.items() if v is not None and not same_value(contract.get(k), v)}
        if not changed:
            return []
        sets = ", ".join(f"{k} = %s" for k in changed)
        self.conn.execute(
            f"update contracts set {sets}, source = 'news', updated_at = now() where id = %s",
            (*changed.values(), contract["id"]),
        )
        return [(contract["id"], "update", k, contract.get(k), v) for k, v in changed.items()]

    def _sign(self, t: dict, player_id: int | None, team_id: int):
        # An extension follows the contract in force this season, not a later one already on file
        # (otherwise a second report of the same extension would create another one after it).
        on_file = self._current(player_id) if player_id else []
        season = current_season()
        in_force = [c for c in on_file if c["end_season"] and (c["start_season"] or 0) <= season <= c["end_season"]]
        current_end = max((c["end_season"] for c in in_force), default=None)
        plan = plan_contract_terms(t, current_end if t["type"] == "extension" else None)
        values = {**plan.values, "team_id": team_id}
        note = "; ".join(plan.derived) or None

        start = values.get("start_season")
        same = None
        if player_id and start:
            same = self.conn.execute(
                f"select id, {', '.join(TRACKED)} from contracts where player_id = %s and start_season = %s",
                (player_id, start),
            ).fetchone()
        elif player_id is None and start:
            same = self.conn.execute(
                f"""select id, {', '.join(TRACKED)} from contracts
                    where player_id is null and lower(player_name) = lower(%s) and start_season = %s""",
                (t["player_name"], start),
            ).fetchone()
        if same:
            existing = dict(zip(["id", *TRACKED], same))
            changes = self._update(existing, values)
            return ("applied" if changes else "no_change"), note, changes

        row = {
            "player_id": player_id, "player_name": t["player_name"], "team_id": team_id,
            "cap_hit": values.get("cap_hit"), "aav": values.get("aav"),
            "start_season": values.get("start_season"), "end_season": values.get("end_season"),
            "expiry_status": values.get("expiry_status"), "clause": values.get("clause"),
            "no_trade_list_size": values.get("no_trade_list_size"), "retained_pct": None,
            "retained_by": None, "status": "active", "contract_type": values["contract_type"],
        }
        contract_id = self.conn.execute(
            f"""insert into contracts ({", ".join(row)}, source) values ({", ".join(["%s"] * len(row))}, 'news')
                returning id""",
            tuple(row.values()),
        ).fetchone()[0]
        changes = [(contract_id, "create", k, None, v) for k, v in row.items() if v is not None and k != "player_id"]
        if player_id is None:
            note = "; ".join(filter(None, [note, "player not yet in our NHL player list; saved by name"]))
        return "applied", note, changes

    def _move(self, t: dict, player_id: int, team_id: int):
        contracts = self._current(player_id)
        if not contracts:
            return "no_change", "no current contract on file to move", []
        values = {"team_id": team_id}
        if t["type"] == "trade" and t.get("retained_pct"):
            retained_by = self.teams.get((t.get("retained_by") or t.get("from_team") or "").upper())
            values["retained_pct"] = t["retained_pct"]
            if retained_by:
                values["retained_by"] = retained_by
        changes = [c for contract in contracts for c in self._update(contract, values)]
        return ("applied" if changes else "no_change"), None, changes

    def _end(self, t: dict, player_id: int):
        contracts = self._current(player_id)
        if not contracts:
            return "no_change", "no current contract on file", []
        changes = self._update(contracts[0], {"status": ENDINGS[t["type"]]})
        return ("applied" if changes else "no_change"), None, changes
