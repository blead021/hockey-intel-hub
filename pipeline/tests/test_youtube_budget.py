from pipeline.sentiment.youtube import DAILY_BUDGET, Collector


def test_budget_stops_further_channels(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test")
    fresh = Collector(None, [], used_today=0)
    assert fresh.unavailable(None) is None
    spent = Collector(None, [], used_today=DAILY_BUDGET - 5)
    spent.units = 5
    assert "budget" in spent.unavailable(None)


def test_order_rotates_but_keeps_every_channel():
    feeds = list(range(10))
    ordered = Collector(None, feeds).order(feeds)
    assert sorted(ordered) == feeds
