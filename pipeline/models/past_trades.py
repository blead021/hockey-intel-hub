"""Past trades for the Trade Builder's comparable trades (CLAUDE.md section 7, Trade Builder).

Usage:
    python -m pipeline.models.past_trades

The contracts job logs each player and draft pick in a trade as its own transaction. This job puts them back
together into deals: transactions between the same two teams reported within 3 days of each other are one trade.
For each player it records his position, age, cap hit, and WAR per 82 games around the trade, so the Trade Builder
can find past trades of similar players. Rebuilt in full on every run (idempotent).

Only completed transactions count; reported deals and rumors are left out, as in the contracts job.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from pipeline.db import connect
from pipeline.jobs import job_run

SAME_TRADE_DAYS = 3
# Transactions the contracts job confirmed as completed (whether or not they changed a contract on file).
KEEP_OUTCOMES = ("applied", "no_change", "skipped_on_file", "skipped_roster_disagrees", "skipped_unmatched",
                 "skipped_unmatched_retried")
ORDINALS = {1: "1st", 2: "2nd", 3: "3rd"}


@dataclass
class Move:
    day: date
    to_team: str
    from_team: str
    kind: str                      # player or pick
    key: str                       # identifies the same item across duplicate reports
    payload: dict
    urls: list[str] = field(default_factory=list)


def pick_label(year: int | None, rnd: int | None, original: str | None) -> str:
    """For example "2027 2nd (TOR)", or "2028 pick (DAL)" when the round was not reported."""
    text = f"{year or ''} {ORDINALS.get(rnd, f'{rnd}th') if rnd else 'pick'}".strip()
    return f"{text}{f' ({original})' if original else ''}"


def group_trades(moves: list[Move]) -> list[list[Move]]:
    """Moves between the same two teams within SAME_TRADE_DAYS of the deal's first report are one trade.
    Duplicate reports of the same item (same player or pick going to the same team) are kept once."""
    by_pair: dict[frozenset, list[Move]] = defaultdict(list)
    for m in moves:
        by_pair[frozenset((m.to_team, m.from_team))].append(m)
    trades = []
    for pair_moves in by_pair.values():
        pair_moves.sort(key=lambda m: m.day)
        current: list[Move] = []
        for m in pair_moves:
            if current and (m.day - current[0].day).days > SAME_TRADE_DAYS:
                trades.append(current)
                current = []
            current.append(m)
        if current:
            trades.append(current)
    out = []
    for t in trades:
        seen, items = set(), []
        for m in t:
            if (m.kind, m.key, m.to_team) not in seen:
                seen.add((m.kind, m.key, m.to_team))
                items.append(m)
        # Different reports name the same player differently ("Lorentz", "Matt Dumba" beside "Mathew Dumba") or
        # leave out a pick's round: an unmatched name is dropped when the trade already has a player with that
        # surname going to the same team, and a pick without a round when the same pick with a round is there.
        surnames = {(m.to_team, surname(m.payload.get("name"))) for m in items if m.kind == "player" and m.payload.get("player_id")}
        picks = {(m.to_team, m.key.split("-")[0], m.key.split("-")[2]) for m in items if m.kind == "pick" and m.key.split("-")[1] != "None"}
        items = [m for m in items
                 if not (m.kind == "player" and not m.payload.get("player_id") and (m.to_team, surname(m.payload.get("name"))) in surnames)
                 and not (m.kind == "pick" and m.key.split("-")[1] == "None" and (m.to_team, m.key.split("-")[0], m.key.split("-")[2]) in picks)]
        out.append(items)
    return sorted(out, key=lambda t: t[0].day)


def surname(name: str | None) -> str:
    return (name or "").strip().lower().split(" ")[-1]


def season_of(day: date) -> int:
    """The season a trade belongs to: from September on, the season about to start."""
    y = day.year if day.month >= 9 else day.year - 1
    return y * 10000 + y + 1


def load_moves(conn) -> list[Move]:
    rows = conn.execute(
        """select e.event_type, e.player_id, e.details, coalesce(e.source_urls, '{}'),
                  (select min(published_at)::date from contract_news n where n.id = any(e.news_ids))
           from contract_events e
           where e.event_type in ('trade', 'draft_pick') and e.event_status = 'completed' and e.outcome = any(%s)""",
        (list(KEEP_OUTCOMES),),
    ).fetchall()
    moves = []
    for kind, player_id, d, urls, day in rows:
        to_team, from_team = (d.get("team") or "").upper(), (d.get("from_team") or "").upper()
        if not day or not to_team or not from_team or to_team == from_team:
            continue
        if kind == "trade":
            name = (d.get("player_name") or "").strip()
            if not name:
                continue
            key = f"p{player_id}" if player_id else name.lower().split()[-1]
            moves.append(Move(day, to_team, from_team, "player", key,
                              {"player_id": player_id, "name": name, "retained_pct": d.get("retained_pct")}, list(urls)))
        else:
            year, rnd = d.get("draft_year"), d.get("round")
            original = (d.get("original_team") or "").upper() or from_team
            moves.append(Move(day, to_team, from_team, "pick", f"{year}-{rnd}-{original}",
                              {"year": year, "round": rnd, "name": pick_label(year, rnd, original)}, list(urls)))
    return moves


def run(conn, counts) -> None:
    teams = dict(conn.execute("select abbrev, id from teams where active").fetchall())
    trades = group_trades(load_moves(conn))
    with conn.transaction():
        conn.execute("delete from past_trades")
        for items in trades:
            a, b = items[0].to_team, items[0].from_team
            if a not in teams or b not in teams:
                counts["trades_unknown_team"] += 1
                continue
            urls = sorted({u for m in items for u in m.urls})[:10]
            trade_id = conn.execute(
                "insert into past_trades (traded_on, team_a, team_b, source_urls) values (%s, %s, %s, %s) returning id",
                (items[0].day, teams[a], teams[b], urls)).fetchone()[0]
            counts["trades"] += 1
            season = season_of(items[0].day)
            for m in items:
                if m.to_team not in teams:
                    continue
                if m.kind == "pick":
                    conn.execute(
                        """insert into past_trade_items (trade_id, to_team_id, kind, name, pick_year, pick_round)
                           values (%s, %s, 'pick', %s, %s, %s)""",
                        (trade_id, teams[m.to_team], m.payload["name"], m.payload["year"], m.payload["round"]))
                    counts["picks"] += 1
                    continue
                pid = m.payload["player_id"]
                info = conn.execute(
                    """select p.first_name || ' ' || p.last_name, p.position,
                              date_part('year', age(%s::date, p.birth_date))::int,
                              (select c.cap_hit from contracts c where c.player_id = p.id
                                 and %s between coalesce(c.start_season, 0) and c.end_season
                               order by c.start_season desc nulls last limit 1),
                              (select sum(w.war) / nullif(sum(w.gp), 0) * 82 from player_war w
                                where w.player_id = p.id and w.season_id in (%s, %s - 10001)),
                              (select sum(w.gp) from player_war w where w.player_id = p.id and w.season_id in (%s, %s - 10001))
                       from players p where p.id = %s""",
                    (m.day, season, season, season, season, season, pid)).fetchone() if pid else None
                name, position, age, cap_hit, war_rate, gp = info or (m.payload["name"], None, None, None, None, None)
                conn.execute(
                    """insert into past_trade_items (trade_id, to_team_id, kind, player_id, name, position, age, cap_hit,
                           retained_pct, war_rate, gp)
                       values (%s, %s, 'player', %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (trade_id, teams[m.to_team], pid, name, position, age, cap_hit, m.payload["retained_pct"],
                     round(war_rate, 2) if war_rate is not None and (gp or 0) >= 10 else None, gp))
                counts["players"] += 1


def main() -> None:
    with job_run("past_trades") as counts, connect() as conn:
        run(conn, counts)
        print(f"past trades ok: {dict(counts)}")


if __name__ == "__main__":
    main()
