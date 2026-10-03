from pipeline.models.war import replacement_rates, war_rows


def test_replacement_and_war_by_hand():
    # One team: 13 regular forwards, then fringe forwards at -0.3 goals per 60 over 400 hours.
    regulars = [{"player_id": i, "grp": "F", "gp": 82, "toi": 1_000_000 - i, "gaa": 5.0} for i in range(13)]
    fringe = [{"player_id": 100 + i, "grp": "F", "gp": 40, "toi": 36_000, "gaa": -3.0} for i in range(40)]
    rates = replacement_rates(regulars + fringe, teams=1, fallback={"F": -0.2, "D": -0.2, "G": -0.2})
    assert round(rates["F"], 3) == -0.3            # 40 x -3.0 goals over 40 x 10 hours
    assert rates["D"] == -0.2 and rates["G"] == -0.2  # no data, so last season's level
    (pid, grp, gp, toi, gaa, gar, war), = war_rows([{"player_id": 1, "grp": "F", "gp": 82, "toi": 3600 * 1000, "gaa": 10.0}], rates, 6.0)
    assert gar == 310.0 and war == round(310 / 6, 3)  # 10 - (-0.3 x 1000 hours)
