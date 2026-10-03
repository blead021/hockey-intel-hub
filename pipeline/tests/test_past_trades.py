from datetime import date

from pipeline.models.past_trades import Move, group_trades, pick_label, season_of


def mv(day, to, frm, kind="player", key="x"):
    return Move(date.fromisoformat(day), to, frm, kind, key, {})


def test_moves_between_two_teams_within_three_days_are_one_trade():
    moves = [
        mv("2026-09-28", "TOR", "CBJ", key="marchenko"),
        mv("2026-09-28", "CBJ", "TOR", key="knies"),
        mv("2026-09-29", "TOR", "CBJ", key="marchenko"),  # a second report of the same player
        mv("2026-09-30", "CBJ", "TOR", "pick", "2027-1-TOR"),
        mv("2026-12-01", "TOR", "CBJ", key="other"),      # months later: a separate trade
        mv("2026-09-28", "PIT", "EDM", key="skinner"),    # another pair of teams
    ]
    trades = group_trades(moves)
    assert [len(t) for t in trades] == [3, 1, 1]
    first = next(t for t in trades if {m.key for m in t} >= {"marchenko"})
    assert {(m.kind, m.key, m.to_team) for m in first} == {
        ("player", "marchenko", "TOR"), ("player", "knies", "CBJ"), ("pick", "2027-1-TOR", "CBJ")}


def test_pick_labels_and_trade_seasons():
    assert pick_label(2027, 2, "TOR") == "2027 2nd (TOR)"
    assert pick_label(2028, None, "DAL") == "2028 pick (DAL)"
    assert pick_label(2029, 5, None) == "2029 5th"
    assert season_of(date(2026, 9, 28)) == 20262027
    assert season_of(date(2026, 3, 1)) == 20252026


def test_duplicate_names_and_roundless_picks_are_merged():
    def m(to, kind, key, **payload):
        return Move(date(2025, 7, 10), to, "DAL" if to == "PIT" else "PIT", kind, key, payload)

    moves = [
        m("PIT", "player", "p1", player_id=1, name="Mathew Dumba"),
        m("PIT", "player", "dumba", player_id=None, name="Matt Dumba"),
        m("PIT", "pick", "2028-2-DAL"),
        m("PIT", "pick", "2028-None-DAL"),
        m("DAL", "player", "p2", player_id=2, name="Vladislav Kolyachonok"),
    ]
    (trade,) = group_trades(moves)
    assert sorted(x.key for x in trade) == ["2028-2-DAL", "p1", "p2"]
