"""Runs the contract update rules against the real database inside a transaction that is rolled back.

Skipped when no database is configured (for example in CI).
"""

import os

import psycopg
import pytest

from pipeline.config import database_url

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DATABASE_URL_UNPOOLED") or os.environ.get("DATABASE_URL")), reason="no database configured"
)


@pytest.fixture
def conn():
    with psycopg.connect(database_url()) as c:
        yield c
        c.rollback()  # nothing from these tests is kept


@pytest.fixture
def setup(conn):
    from pipeline.contracts.apply import Applier

    teams = dict(conn.execute("select abbrev, id from teams where active").fetchall())
    player_id, name, team = conn.execute(
        """select p.id, p.first_name || ' ' || p.last_name, t.abbrev from players p join teams t on t.id = p.current_team_id
           where p.position = 'C' and t.active order by p.id limit 1"""
    ).fetchone()
    other = next(code for code in teams if code != team)
    # Start from a known state; real contracts for this player come back when the transaction rolls back.
    conn.execute("delete from contracts where player_id = %s", (player_id,))
    conn.execute(
        """insert into contracts (player_id, player_name, team_id, cap_hit, start_season, end_season, expiry_status,
               clause, retained_pct, status, source)
           values (%s, %s, %s, 5000000, 20232024, 20262027, 'UFA', 'NTC', 0, 'active', 'starting_file')""",
        (player_id, name, teams[team]),
    )
    return Applier(conn, None, "test-model", teams), player_id, name, team, other, teams


def _t(**kw):
    base = {"type": "signing", "status": "completed", "player_name": "X", "team": None, "from_team": None,
            "cap_hit": None, "total_value": None, "years": None, "start_season": None, "end_season": None,
            "expiry_status": None, "clause": None, "no_trade_list_size": None, "retained_pct": None,
            "retained_by": None, "items": [1], "evidence": "e"}
    return {**base, **kw}


NEWS = [{"id": "gn:test", "url": "https://news.example/item"}]


def _contracts(conn, player_id):
    return conn.execute(
        """select start_season, end_season, cap_hit, team_id, retained_pct, retained_by, clause, status, source
           from contracts where player_id = %s order by start_season""",
        (player_id,),
    ).fetchall()


def test_full_sequence_applies_rules_and_logs_every_change(conn, setup):
    applier, pid, name, team, other, teams = setup

    # 1. Extension: new contract after the current one ends; cap hit from total / years; clause unknown.
    assert applier.apply(_t(type="extension", player_name=name, team=team, total_value=32_000_000, years=4), NEWS) == "applied"
    rows = _contracts(conn, pid)
    assert rows[1][:4] == (20272028, 20302031, 8_000_000, teams[team]) and rows[1][6] is None

    # 2. Same extension reported again by another outlet: nothing changes.
    assert applier.apply(_t(type="extension", player_name=name, team=team, total_value=32_000_000, years=4), NEWS) == "no_change"

    # 3. Trade with retained salary: both current and future contracts move; terms on file are kept.
    outcome = applier.apply(_t(type="trade", player_name=name, team=other, from_team=team, retained_pct=50, retained_by=team), NEWS)
    assert outcome == "applied"
    rows = _contracts(conn, pid)
    assert all(r[3] == teams[other] for r in rows)
    assert float(rows[0][4]) == 50 and rows[0][5] == teams[team]
    assert rows[0][2] == 5_000_000 and rows[0][6] == "NTC"  # not mentioned, so kept

    # 4. A rumor changes nothing.
    assert applier.apply(_t(type="trade", status="rumor", player_name=name, team=team), NEWS) == "skipped_unconfirmed"
    assert all(r[3] == teams[other] for r in _contracts(conn, pid))

    # 5. Buyout ends the current contract only.
    assert applier.apply(_t(type="buyout", player_name=name), NEWS) == "applied"
    statuses = [r[7] for r in _contracts(conn, pid)]
    assert statuses.count("bought_out") == 1

    # Every change is logged with its source.
    changes = conn.execute(
        """select c.action, c.field, c.old_value, c.new_value, c.source_urls from contract_changes c
           join contract_events e on e.id = c.event_id where e.player_name = %s order by c.id""",
        (name,),
    ).fetchall()
    fields = [(a, f) for a, f, *_ in changes]
    assert ("create", "cap_hit") in fields and ("update", "team_id") in fields and ("update", "status") in fields
    assert all(urls == ["https://news.example/item"] for *_, urls in changes)
    events = conn.execute(
        "select outcome from contract_events where player_name = %s order by id", (name,)
    ).fetchall()
    assert [e[0] for e in events] == ["applied", "no_change", "applied", "skipped_unconfirmed", "applied"]


def test_prospect_entry_level_deal_is_saved_by_name_with_unknowns(conn, setup):
    applier, _, _, team, _, teams = setup
    t = _t(type="entry_level", player_name="Zzyzx Prospectington", team=team, years=3, start_season="2026-27")
    assert applier.apply(t, NEWS) == "applied"
    row = conn.execute(
        """select player_id, team_id, cap_hit, start_season, end_season, contract_type, source from contracts
           where player_name = 'Zzyzx Prospectington'"""
    ).fetchone()
    assert row == (None, teams[team], None, 20262027, 20282029, "entry_level", "news")
    note = conn.execute(
        "select outcome_note from contract_events where player_name = 'Zzyzx Prospectington'"
    ).fetchone()[0]
    assert "saved by name" in note


def test_unknown_team_is_skipped(conn, setup):
    applier, _, name, *_ = setup
    assert applier.apply(_t(type="signing", player_name=name, team="XYZ"), NEWS) == "skipped_unmatched"


def test_backfill_only_adds_missing_contracts_still_in_force(conn, setup):
    from pipeline.contracts.apply import Applier

    applier, player_id, name, team, other, teams = setup
    backfill = Applier(conn, None, "test", teams, create_only=True)
    before = _contracts(conn, player_id)
    # A player with a contract on file is never changed, even by a signing or a trade.
    assert backfill.apply(_t(type="extension", player_name=name, team=team, cap_hit=9_000_000, years=3), NEWS) == "skipped_on_file"
    # He is on his team's NHL roster, so a trade elsewhere or a buyout from old news is not recorded.
    assert backfill.apply(_t(type="trade", player_name=name, team=other, from_team=team), NEWS) == "skipped_roster_disagrees"
    assert backfill.apply(_t(type="buyout", player_name=name, team=team), NEWS) == "skipped_roster_disagrees"
    assert _contracts(conn, player_id) == before
    # A depth player with no contract: an expired deal is skipped, one still in force is added.
    old = _t(type="signing", player_name="Backfill Testplayer", team=team, cap_hit=775_000,
             start_season="2022-23", end_season="2023-24")
    assert backfill.apply(old, NEWS) == "skipped_expired"
    new = _t(type="signing", player_name="Backfill Testplayer", team=team, cap_hit=800_000,
             start_season="2025-26", end_season="2027-28")
    assert backfill.apply(new, NEWS) == "applied"
    assert backfill.apply(new, NEWS) == "skipped_on_file"


def test_roster_moves_set_status_and_never_go_backwards(conn, setup):
    from datetime import datetime, timezone

    applier, player_id, name, team, other, teams = setup
    conn.execute("delete from player_status where player_id = %s", (player_id,))
    day = lambda d: [{"id": f"gn:{d}", "url": None, "published_at": datetime(2026, 10, d, tzinfo=timezone.utc)}]
    status = lambda: conn.execute("select status, since from player_status where player_id = %s", (player_id,)).fetchone()
    before = _contracts(conn, player_id)

    assert applier.apply(_t(type="assigned_to_minors", player_name=name, team=team), day(5)) == "applied"
    assert status()[0] == "minors"
    # An older headline (placed on IR on the 3rd) does not overwrite the newer assignment.
    assert applier.apply(_t(type="injured_reserve", player_name=name, team=team), day(3)) == "no_change"
    assert status()[0] == "minors"
    assert applier.apply(_t(type="recalled", player_name=name, team=team), day(8)) == "applied"
    assert status()[0] == "nhl" and str(status()[1]) == "2026-10-08"
    # Roster moves never touch the contract.
    assert _contracts(conn, player_id) == before
