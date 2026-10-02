import math

import pytest

from pipeline.models.xg_features import attacking_goal_x, distance_angle, shot_rows, skaters, zone_from

HOME, AWAY = 1, 2


def test_attacking_goal_follows_the_defended_side():
    assert attacking_goal_x(True, "left") == 89 and attacking_goal_x(False, "left") == -89
    assert attacking_goal_x(True, "right") == -89 and attacking_goal_x(True, None) is None


def test_distance_and_angle_on_paper():
    assert distance_angle(79, 0, 89) == (10, 0)                       # 10 feet straight out
    d, a = distance_angle(59, 30, 89)                                 # 30 out, 30 across: 45 degrees
    assert d == pytest.approx(math.hypot(30, 30)) and a == pytest.approx(45)
    assert distance_angle(-79, -10, -89)[1] == pytest.approx(45)      # same geometry at the other end
    assert distance_angle(89, 5, 89)[1] == 90                         # on the goal line
    assert distance_angle(94, 5, 89)[1] == pytest.approx(135)         # from behind the net


def test_zones_and_skaters():
    assert zone_from(60, 89) == "O" and zone_from(-60, 89) == "D" and zone_from(10, 89) == "N"
    assert skaters("1451", shooting_is_home=True) == (5, 4, 1)        # home power play
    assert skaters("0651", shooting_is_home=True) == (5, 6, 0)        # away goalie pulled: empty net for home


def _play(event_id, kind, t, team_shooter, x=None, y=None, situation="1551", period=1, **extra):
    details = {"xCoord": x, "yCoord": y, "eventOwnerTeamId": extra.pop("owner", None)}
    if kind == "goal":
        details["scoringPlayerId"] = team_shooter
    elif team_shooter:
        details["shootingPlayerId"] = team_shooter
    details.update(extra)
    return {"eventId": event_id, "sortOrder": event_id, "typeDescKey": kind,
            "timeInPeriod": f"{t // 60:02d}:{t % 60:02d}", "situationCode": situation,
            "homeTeamDefendingSide": "left", "periodDescriptor": {"number": period, "periodType": "REG"},
            "details": details}


PBP = {
    "id": 2025020001,
    "homeTeam": {"id": HOME},
    "awayTeam": {"id": AWAY},
    "rosterSpots": [{"playerId": 11, "teamId": HOME}, {"playerId": 12, "teamId": HOME}, {"playerId": 21, "teamId": AWAY}],
    "plays": [
        _play(1, "period-start", 0, None),
        _play(2, "faceoff", 0, None, x=0, y=0, owner=HOME),
        _play(3, "takeaway", 10, None, x=-40, y=0, owner=HOME),           # home, in its own zone
        _play(4, "shot-on-goal", 13, 11, x=70, y=5, shotType="wrist"),   # 3s after a D-zone event: rush
        _play(5, "goal", 15, 12, x=85, y=0, shotType="tip-in"),          # 2s after own shot: rebound
        _play(6, "blocked-shot", 30, 21, x=-50, y=0),                     # blocked: not a row
        _play(7, "missed-shot", 40, 21, x=-60, y=20, shotType="slap"),   # away, trailing 0-1
        _play(8, "shot-on-goal", 50, 11, x=80, y=0, situation="0101"),   # penalty shot: left out
        _play(9, "shot-on-goal", 59, 21, x=-70, y=0, situation="1560"),  # home goalie pulled: empty net
        _play(10, "shot-on-goal", 70, 11),                                # no coordinates: left out
    ],
}


def test_rows_cover_unblocked_shots_with_coordinates_only():
    rows = shot_rows(PBP)
    assert [r.event_id for r in rows] == [4, 5, 7, 9]
    assert [r.is_goal for r in rows] == [0, 1, 0, 0]


def test_rush_rebound_score_and_empty_net():
    rush_shot, rebound_goal, slap, empty = shot_rows(PBP)
    assert rush_shot.features["rush"] == 1 and rush_shot.features["rebound"] == 0
    assert rebound_goal.features["rebound"] == 1 and rebound_goal.features["seconds_since_prior"] == 2
    assert rebound_goal.features["shot_type"] == "tip-in"
    assert slap.features["score_diff"] == -1 and slap.features["prior_event"] == "blocked-shot"
    assert slap.features["prior_same_team"] == 1      # the blocked shot was also the away team's
    assert slap.shooting_team == AWAY and slap.defending_team == HOME
    assert empty.features["empty_net"] == 1 and empty.features["defending_skaters"] == 6
    assert rush_shot.features["distance"] == pytest.approx(math.hypot(19, 5))
