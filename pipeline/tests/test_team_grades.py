from pipeline.models.team_grades import compute, grade, zscores


def test_grade_boundaries():
    assert [grade(z) for z in (-1.5, -1.0, -0.5, -0.4, 0.0, 0.39, 0.4, 0.99, 1.0, 2.0)] == [-2, -2, -1, 0, 0, 0, 1, 1, 2, 2]


def test_zscores_flip_when_lower_is_better():
    values = {1: 2.0, 2: 3.0, 3: 4.0}
    up, down = zscores(values, True), zscores(values, False)
    assert up[3] > 0 > up[1] and down[1] > 0 > down[3]
    assert zscores({1: 5.0, 2: 5.0}, True) == {1: 0.0, 2: 0.0}


def test_compute_by_hand():
    base = {"hits": 20, "blocks": 10, "toi_5v5": 3600 * 40, "pp_pct": 0.2, "pk_pct": 0.8, "gsax": 0}
    totals = [
        {**base, "team_id": 1, "gp": 10, "goals_for": 40, "primary_assists": 20, "xga_5v5": 100},
        {**base, "team_id": 2, "gp": 10, "goals_for": 30, "primary_assists": 20, "xga_5v5": 80},
        {**base, "team_id": 3, "gp": 10, "goals_for": 20, "primary_assists": 20, "xga_5v5": 120},
    ]
    out = compute(totals)
    assert out["goal_scoring"][1][0] == 4.0 and out["goal_scoring"][1][2] == 2   # z = +1.22
    assert out["goal_scoring"][3][2] == -2
    assert out["defense_5v5"][2][1] > 0                                           # fewest xGA is best
    assert out["playmaking"][1][1] == 0.0                                         # all equal
