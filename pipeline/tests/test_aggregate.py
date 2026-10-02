from datetime import date

import pytest

from pipeline.sentiment.aggregate import MIN_MENTIONS, daily_scores, weight

DAY = date(2026, 10, 20)


def test_weight_halves_every_seven_days():
    assert weight(0) == 1 and weight(7) == pytest.approx(0.5) and weight(14) == pytest.approx(0.25)


def test_score_is_50_plus_50_times_weighted_mean():
    # Five fan mentions today at +0.4: score 70. All audiences together give the same.
    mentions = [(1, "fan", DAY, 0.4, False)] * 5
    rows = {(r[2]): r for r in daily_scores(mentions, [DAY])}
    assert rows["fan"][3] == 70.0 and rows["all"][3] == 70.0
    assert rows["fan"][4:] == (5, 5, 0)


def test_recent_mentions_count_more():
    # One +1 today and one -1 a week ago (half weight): mean = (1 - 0.5) / 1.5 = 0.333.
    mentions = [(1, "fan", DAY, 1.0, False), (1, "fan", date(2026, 10, 13), -1.0, False)] + \
               [(1, "fan", DAY, 0.0, False)] * (MIN_MENTIONS - 2)
    fan = next(r for r in daily_scores(mentions, [DAY]) if r[2] == "fan")
    # weights: today 1 x (MIN_MENTIONS - 1) mentions, a week ago 0.5
    expected_mean = (1.0 - 0.5) / ((MIN_MENTIONS - 1) + 0.5)
    assert fan[3] == round(50 + 50 * expected_mean, 2)


def test_too_few_mentions_show_no_score_but_still_count_trade_talk():
    rows = daily_scores([(1, "beat_writer", DAY, -0.5, True)] * 2, [DAY])
    writer = next(r for r in rows if r[2] == "beat_writer")
    assert writer[3] is None and writer[6] == 2


def test_mentions_older_than_the_window_are_ignored():
    assert daily_scores([(1, "fan", date(2026, 9, 1), 1.0, False)], [DAY]) == []
