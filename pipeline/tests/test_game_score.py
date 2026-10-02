import pytest

from pipeline.metrics.game_score import Rates, SkaterGame, skater_components

# League rates per second: 2.4 xGF per 60 at 5v5, +6 net xG per 60 on the PP, -6 on the PK,
# and 0.9 primary assists per 60 minutes of ice time.
RATES = Rates(ev_xgf=2.4 / 3600, pp_net=6.0 / 3600, sh_net=-6.0 / 3600, a1=0.9 / 3600)


def game(**kw):
    base = dict(toi_5v5=900, xgf=0.6, xga=0.6, pp_toi=120, pp_xgf=0.2, pp_xga=0.0, pk_toi=120, sh_xgf=0.0,
                sh_xga=0.2, toi_all=1140, goals=0, ixg=0.0, a1=0, drawn=0, taken=0, fow=0, fol=0)
    return SkaterGame(**{**base, **kw})


def test_an_exactly_average_game_scores_zero():
    # 15 min at 5v5 at the league rate (0.6 xG each way), 2 min PP at +0.2, 2 min PK at -0.2,
    # and 19 min of ice time with 0.285 expected primary assists: playmaking is the only non-zero part.
    c = skater_components(game(), RATES, factor=1.0)
    assert c.ev_offense == pytest.approx(0) and c.ev_defense == pytest.approx(0)
    assert c.power_play == pytest.approx(0) and c.penalty_kill == pytest.approx(0)
    assert c.playmaking == pytest.approx(-0.5 * 0.285)


def test_hand_worked_game():
    c = skater_components(
        game(xgf=1.1, xga=0.4, goals=2, ixg=0.7, a1=1, drawn=1, taken=0, fow=12, fol=8), RATES, factor=1.0)
    assert c.ev_offense == pytest.approx(0.2 * (1.1 - 0.6))       # +0.10
    assert c.ev_defense == pytest.approx(0.2 * (0.6 - 0.4))       # +0.04
    assert c.finishing == pytest.approx(2 - 0.7)                  # +1.30
    assert c.playmaking == pytest.approx(0.5 * (1 - 0.285))       # +0.3575
    assert c.penalties == pytest.approx(0.19)
    assert c.faceoffs == pytest.approx(0.04)
    assert c.total == pytest.approx(0.10 + 0.04 + 1.30 + 0.3575 + 0.19 + 0.04)


def test_season_factor_scales_xg_terms_only():
    c = skater_components(game(goals=1, ixg=1.0), RATES, factor=0.9)
    assert c.finishing == pytest.approx(1 - 0.9)
    assert c.ev_offense == pytest.approx(0.2 * (0.6 * 0.9 - 0.6))


def test_game_without_shift_chart_keeps_individual_parts():
    c = skater_components(game(xgf=None, xga=None, pp_xgf=None, pp_xga=None, sh_xgf=None, sh_xga=None, goals=1, ixg=0.2),
                          RATES, factor=1.0)
    assert (c.ev_offense, c.ev_defense, c.power_play, c.penalty_kill) == (0, 0, 0, 0)
    assert c.finishing == pytest.approx(0.8)
