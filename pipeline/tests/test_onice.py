"""A two-minute game built by hand, so every on-ice number can be checked on paper.

Home team 1 (goalie 30, skaters 11-16), away team 2 (goalie 40, skaters 21-25).
Everyone plays 0:00-2:00 except home 15 (0:00-1:00) and home 16 (1:00-2:00), who change at 1:00.
Home defends the left end, so a faceoff at x=69 is in the home team's offensive zone.

Events (all 5v5 unless noted):
  0:00 faceoff at center
  0:30 home 11 shot on goal
  0:50 home 11 shot, but at 5-on-4: ignored
  1:00 away 21 missed shot, at the second of the 15-for-16 change: 15 was on, 16 was not
  1:00 faceoff in the home offensive zone: 16 starts his shift there
  1:30 away 22 shot blocked by home 12
  1:40 home 16 goal
  1:50 home 13 shot blocked by his own teammate 14: still a home attempt (NHL.com counts it for the
       other team; we count it for the shooter's team)
"""

from pipeline.metrics.onice import compute_game, zone_for

HOME, AWAY = 1, 2


def _roster():
    spots = [{"playerId": 30, "teamId": HOME, "positionCode": "G"}, {"playerId": 40, "teamId": AWAY, "positionCode": "G"}]
    spots += [{"playerId": p, "teamId": HOME, "positionCode": "C"} for p in range(11, 17)]
    spots += [{"playerId": p, "teamId": AWAY, "positionCode": "C"} for p in range(21, 26)]
    return spots


def _shift(player, team, start, end):
    return {"playerId": player, "teamId": team, "period": 1, "typeCode": 517,
            "startTime": f"{start // 60:02d}:{start % 60:02d}", "endTime": f"{end // 60:02d}:{end % 60:02d}"}


def _play(kind, t, situation="1551", **details):
    return {"typeDescKey": kind, "timeInPeriod": f"{t // 60:02d}:{t % 60:02d}", "situationCode": situation,
            "periodDescriptor": {"number": 1, "periodType": "REG"}, "homeTeamDefendingSide": "left", "details": details}


PBP = {
    "homeTeam": {"id": HOME},
    "awayTeam": {"id": AWAY},
    "rosterSpots": _roster(),
    "plays": [
        _play("faceoff", 0, xCoord=0),
        _play("shot-on-goal", 30, shootingPlayerId=11),
        _play("shot-on-goal", 50, situation="1451", shootingPlayerId=11),
        _play("missed-shot", 60, shootingPlayerId=21),
        _play("faceoff", 60, xCoord=69),
        _play("blocked-shot", 90, shootingPlayerId=22, blockingPlayerId=12, reason="blocked"),
        _play("goal", 100, scoringPlayerId=16),
        _play("blocked-shot", 110, shootingPlayerId=13, blockingPlayerId=14, reason="teammate-blocked"),
    ],
}

SHIFTS = {"data": (
    [_shift(30, HOME, 0, 120), _shift(40, AWAY, 0, 120)]
    + [_shift(p, HOME, 0, 120) for p in (11, 12, 13, 14)]
    + [_shift(15, HOME, 0, 60), _shift(16, HOME, 60, 120)]
    + [_shift(p, AWAY, 0, 120) for p in range(21, 26)]
    + [{**_shift(16, HOME, 100, 100), "typeCode": 505}]  # goal marker rows are not shifts
)}


def line(result, player):
    return result.players[player][1]


def test_team_totals():
    r = compute_game(PBP, SHIFTS)
    home, away = r.teams[HOME], r.teams[AWAY]
    assert (home.toi, home.cf, home.ca, home.ff, home.fa, home.sf, home.sa, home.gf, home.ga) == (120, 3, 2, 2, 1, 2, 0, 1, 0)
    assert (away.cf, away.ca, away.ff, away.fa, away.gf, away.ga) == (2, 3, 1, 2, 0, 1)


def test_player_on_for_event_at_the_change_second_is_the_one_leaving():
    r = compute_game(PBP, SHIFTS)
    p15, p16 = line(r, 15), line(r, 16)
    assert (p15.toi, p15.cf, p15.ca, p15.ff, p15.fa, p15.sf, p15.gf) == (60, 1, 1, 1, 1, 1, 0)
    assert (p16.toi, p16.cf, p16.ca, p16.ff, p16.fa, p16.sf, p16.gf) == (60, 2, 1, 1, 0, 1, 1)


def test_full_game_skater_and_opponent():
    r = compute_game(PBP, SHIFTS)
    p11, p21 = line(r, 11), line(r, 21)
    assert (p11.toi, p11.cf, p11.ca, p11.ff, p11.fa, p11.gf, p11.ga) == (120, 3, 2, 2, 1, 1, 0)
    assert (p21.toi, p21.cf, p21.ca, p21.ff, p21.fa, p21.gf, p21.ga) == (120, 2, 3, 1, 2, 0, 1)


def test_zone_starts_and_goalies_excluded():
    r = compute_game(PBP, SHIFTS)
    assert (line(r, 11).nz, line(r, 11).oz) == (1, 0)
    assert (line(r, 16).oz, line(r, 16).nz) == (1, 0)
    assert line(r, 21).dz == 0 and line(r, 21).nz == 1  # away 21 did not start a shift at 1:00
    assert 30 not in r.players and 40 not in r.players


def test_shift_counts_drive_5v5_time():
    # Take home 15 off the shift chart: home has 4 skaters for the first minute, so only 60s are 5v5.
    shifts = {"data": [s for s in SHIFTS["data"] if s["playerId"] != 15]}
    r = compute_game(PBP, shifts)
    assert r.teams[HOME].toi == 60 and line(r, 11).toi == 60


def test_zone_from_coordinates():
    assert zone_for(True, 69, "left") == "O" and zone_for(False, 69, "left") == "D"
    assert zone_for(True, -69, "left") == "D" and zone_for(True, 20, "left") == "N"
    assert zone_for(True, 69, "right") == "D" and zone_for(True, None, "left") is None


def test_expected_goals_and_high_danger_chances():
    plays = [{**p, "eventId": n} for n, p in enumerate(PBP["plays"])]
    pbp = {**PBP, "plays": plays}
    # eventIds: 1 = 0:30 home shot, 3 = 1:00 away miss, 6 = 1:40 home goal, 7 = 1:50 blocked (never has xG)
    xg = {1: 0.10, 3: 0.20, 6: 0.50, 7: 0.90}
    r = compute_game(pbp, SHIFTS, xg)
    home = r.teams[HOME]
    assert (round(home.xgf, 2), round(home.xga, 2), home.hdcf, home.hdca) == (0.60, 0.20, 1, 1)
    p15, p16 = line(r, 15), line(r, 16)
    assert (round(p15.xgf, 2), round(p15.xga, 2)) == (0.10, 0.20)   # on for 0:30 and 1:00
    assert (round(p16.xgf, 2), p16.hdcf) == (0.50, 1)               # on for the 1:40 goal only


def test_shooting_and_goalie_totals():
    from types import SimpleNamespace

    from pipeline.metrics.onice import shooting_and_goalies

    def row(event_id, shooter, goal, situation="1551", goalie=40, empty=0):
        return SimpleNamespace(event_id=event_id, shooter_id=shooter, shooting_team=HOME, defending_team=AWAY,
                               goalie_id=goalie, is_goal=goal, situation=situation, features={"empty_net": empty})

    rows = [row(1, 11, 0), row(2, 11, 1, situation="1451"), row(3, 12, 1, goalie=None, empty=1), row(4, 11, 0)]
    shooters, goalies = shooting_and_goalies(rows, {1: 0.1, 2: 0.3, 3: 0.8})  # event 4 has no xG: skipped
    s11 = shooters[11]
    assert (s11.shots, s11.goals, round(s11.ixg, 2), s11.shots_5v5, s11.goals_5v5, round(s11.ixg_5v5, 2)) == (2, 1, 0.4, 1, 0, 0.1)
    assert (shooters[12].goals, round(shooters[12].ixg, 2)) == (1, 0.8)
    g = goalies[40]  # the empty-net goal does not count against him
    assert (g.shots_faced, g.goals_against, round(g.xga, 2)) == (2, 1, 0.4)
