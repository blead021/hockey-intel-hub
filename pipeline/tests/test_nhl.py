from datetime import date

import pytest

from pipeline.ingest import nhl
from pipeline.ingest.nhl_games import check_game, goalie_goals
from pipeline.ingest.nightly import current_season


def _skater(pid, pos="C", goals=0, assists=0, toi="15:30"):
    return {
        "playerId": pid, "position": pos, "goals": goals, "assists": assists, "sog": 2, "hits": 1,
        "blockedShots": 0, "pim": 0, "plusMinus": 1, "giveaways": 0, "takeaways": 1, "shifts": 20, "toi": toi,
    }


BOX = {
    "gameState": "OFF",
    "gameOutcome": {"lastPeriodType": "OT"},
    "awayTeam": {"id": 4, "score": 2},
    "homeTeam": {"id": 1, "score": 3},
    "playerByGameStats": {
        "awayTeam": {
            "forwards": [_skater(10, goals=2)],
            "defense": [_skater(11, pos="D", assists=1)],
            "goalies": [
                {"playerId": 30, "toi": "62:49", "starter": True, "decision": "O", "shotsAgainst": 44,
                 "saves": 41, "goalsAgainst": 3, "evenStrengthShotsAgainst": "33/35", "powerPlayShotsAgainst": "8/8"},
                {"playerId": 31, "toi": "00:00", "goalsAgainst": 0},
            ],
        },
        "homeTeam": {
            "forwards": [_skater(20, goals=2), _skater(21, pos="L", assists=2)],
            "defense": [_skater(22, pos="D", goals=1, assists=2)],
            "goalies": [{"playerId": 40, "toi": "63:23", "starter": True, "decision": "W", "shotsAgainst": 25,
                         "saves": 23, "goalsAgainst": 2}],
        },
    },
}


def _goal(scorer, team, a1=None, a2=None, period="REG"):
    return {"typeDescKey": "goal", "periodDescriptor": {"periodType": period},
            "details": {"scoringPlayerId": scorer, "eventOwnerTeamId": team,
                        "assist1PlayerId": a1, "assist2PlayerId": a2}}


PBP = {
    "plays": [
        _goal(20, 1, a1=21, a2=22),
        _goal(10, 4, a1=11),
        _goal(20, 1, a1=22),
        _goal(10, 4),
        _goal(22, 1, a1=21),
        _goal(20, 1, period="SO"),  # shootout goals carry no assists and are ignored
        {"typeDescKey": "faceoff", "details": {"winningPlayerId": 20, "losingPlayerId": 10}},
        {"typeDescKey": "faceoff", "details": {"winningPlayerId": 10, "losingPlayerId": 20}},
        {"typeDescKey": "faceoff", "details": {"winningPlayerId": 20, "losingPlayerId": 10}},
    ],
    "rosterSpots": [
        {"playerId": 20, "firstName": {"default": "Quinn"}, "lastName": {"default": "Hughes"}, "positionCode": "D", "teamId": 1},
        {"playerId": 40, "firstName": {"default": "Jake"}, "lastName": {"default": "Allen"}, "positionCode": "G", "teamId": 1},
    ],
}


def test_toi_seconds():
    assert nhl.toi_seconds("63:23") == 3803
    assert nhl.toi_seconds("00:00") == 0
    assert nhl.toi_seconds(None) == 0


def test_boxscore_skips_backup_goalie_and_splits_shots():
    skaters, goalies = nhl.parse_boxscore(BOX)
    assert len(skaters) == 5
    assert [g.player_id for g in goalies] == [30, 40]  # 31 dressed but never played
    loser = goalies[0]
    assert loser.decision == "O"
    assert (loser.ev_shots_against, loser.ev_ga) == (35, 2)
    assert (loser.pp_shots_against, loser.pp_ga) == (8, 0)
    assert loser.toi_sec == 3769


def test_pbp_credits_count_primary_and_secondary_assists_and_faceoffs():
    credits = nhl.pbp_credits(PBP)
    assert credits[21] == {"a1": 2, "a2": 0, "fow": 0, "fol": 0}
    assert credits[22] == {"a1": 1, "a2": 1, "fow": 0, "fol": 0}
    assert credits[20]["fow"] == 2 and credits[20]["fol"] == 1
    assert credits[10]["fow"] == 1 and credits[10]["fol"] == 2


def test_check_game_passes_consistent_game_and_reports_problems():
    skaters, _ = nhl.parse_boxscore(BOX)
    credits = nhl.pbp_credits(PBP)
    for s in skaters:
        c = credits.get(s.player_id, {})
        s.a1, s.a2 = c.get("a1", 0), c.get("a2", 0)
    assert check_game(BOX, skaters) == []

    skaters[0].g = 1
    problems = check_game(BOX, skaters)
    assert any("skater goals 1, expected 2" in p for p in problems)


def test_goalie_goal_is_not_a_missing_skater_goal():
    box = {**BOX, "homeTeam": {"id": 1, "score": 4}}
    pbp = {"plays": PBP["plays"] + [_goal(40, 1)]}
    skaters, _ = nhl.parse_boxscore(box)
    for s in skaters:
        c = nhl.pbp_credits(PBP).get(s.player_id, {})
        s.a1, s.a2 = c.get("a1", 0), c.get("a2", 0)
    assert goalie_goals(pbp, {40}) == {1: 1}
    assert check_game(box, skaters, goalie_goals(pbp, {40})) == []
    assert check_game(box, skaters) != []


def test_shootout_winner_score_includes_the_extra_goal():
    box = {**BOX, "gameOutcome": {"lastPeriodType": "SO"}, "homeTeam": {"id": 1, "score": 4}}
    skaters, _ = nhl.parse_boxscore(box)
    for s in skaters:
        c = nhl.pbp_credits(PBP).get(s.player_id, {})
        s.a1, s.a2 = c.get("a1", 0), c.get("a2", 0)
    assert check_game(box, skaters) == []


def test_missing_field_names_the_field():
    with pytest.raises(nhl.NhlSchemaError, match="missing field 'playerByGameStats'"):
        nhl.parse_boxscore({})


def test_club_schedule_keeps_regular_season_and_playoffs_only():
    body = {"games": [
        {"id": 1, "season": 20262027, "gameType": 1, "gameDate": "2026-09-20", "gameState": "OFF",
         "homeTeam": {"id": 1}, "awayTeam": {"id": 2}},
        {"id": 2, "season": 20262027, "gameType": 2, "gameDate": "2026-10-01", "gameState": "OFF",
         "homeTeam": {"id": 1, "score": 3}, "awayTeam": {"id": 2, "score": 2}, "venue": {"default": "Arena"},
         "gameOutcome": {"lastPeriodType": "REG"}},
    ]}
    [game] = nhl.parse_club_schedule(body)
    assert (game.id, game.home_score, game.venue, game.last_period_type) == (2, 3, "Arena", "REG")


def test_pbp_players_have_full_names():
    players = nhl.pbp_players(PBP)
    assert players[0].first_name == "Quinn" and players[0].last_name == "Hughes"


def test_edge_parse_tolerates_missing_sections():
    e = nhl.parse_edge({"skatingSpeed": {"speedMax": {"imperial": 24.6, "percentile": 0.99},
                                          "burstsOver20": {"value": 681}}}, 97)
    assert (e.top_speed_mph, e.bursts_20plus, e.bursts_22plus, e.max_shot_speed_mph) == (24.6, 681, None, None)


def test_current_season_rolls_over_in_september():
    assert current_season(date(2026, 10, 2)) == 20262027
    assert current_season(date(2027, 3, 1)) == 20262027
    assert current_season(date(2027, 9, 1)) == 20272028
