import json
from types import SimpleNamespace

from pipeline.contracts import extract as ex
from pipeline.contracts.apply import plan_contract_terms, same_value, season_id, shift
from pipeline.contracts.news import NewsItem, is_candidate, parse_results

RESULTS_XML = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Ducks Ink Luneau to Six-Year Contract Extension | Anaheim Ducks - NHL.com</title>
<link>https://news.google.com/a</link><pubDate>Thu, 01 Oct 2026 15:00:00 GMT</pubDate>
<source url="https://www.nhl.com">NHL.com</source></item>
<item><title>Ducks beat Kings in opener - NHL.com</title><link>https://news.google.com/b</link>
<pubDate>Thu, 01 Oct 2026 15:00:00 GMT</pubDate><source url="https://www.nhl.com">NHL.com</source></item>
</channel></rss>"""


def _item(title, outlet="NHL.com", url="https://news.google.com/x"):
    return NewsItem(id="k", title=title, outlet=outlet, url=url, published_at=None, query="q")


def test_parse_results_strips_outlet_and_keys_on_headline():
    signing, game = parse_results(RESULTS_XML, "q")
    assert signing.title == "Ducks Ink Luneau to Six-Year Contract Extension | Anaheim Ducks"
    assert signing.outlet == "NHL.com" and signing.id.startswith("gn:")
    assert is_candidate(signing) and not is_candidate(game)


def test_contract_database_sites_are_never_used():
    assert not is_candidate(_item("Player signs extension", outlet="PuckPedia"))
    assert not is_candidate(_item("Player signs extension", outlet="Spotrac"))
    assert not is_candidate(_item("Player signs extension", outlet="x", url="https://capwages.com/a"))
    assert is_candidate(_item("Flyers acquire Goyette from Kraken"))


def test_seasons():
    assert season_id("2027-28") == 20272028 and season_id("2030-2031") == 20302031
    assert season_id("2027-29") is None and season_id(None) is None and season_id("next year") is None
    assert shift(20262027, 1) == 20272028 and shift(20302031, -5) == 20252026


def _t(**kw):
    base = {"type": "signing", "status": "completed", "player_name": "X", "team": "ANA", "from_team": None,
            "cap_hit": None, "total_value": None, "years": None, "start_season": None, "end_season": None,
            "expiry_status": None, "clause": None, "no_trade_list_size": None, "retained_pct": None,
            "retained_by": None, "items": [1], "evidence": "e"}
    return {**base, **kw}


def test_plan_uses_stated_terms_and_only_arithmetic():
    plan = plan_contract_terms(_t(type="extension", total_value=43_200_000, years=6, end_season="2032-33"), None)
    assert plan.values["cap_hit"] == 7_200_000 and plan.values["aav"] == 7_200_000
    assert plan.values["start_season"] == 20272028 and plan.values["end_season"] == 20322033
    assert "cap hit: total value divided by years" in plan.derived
    assert plan.values["contract_type"] == "extension"
    assert "clause" not in plan.values and "expiry_status" not in plan.values  # unknown stays unknown


def test_extension_starts_after_the_contract_on_file():
    plan = plan_contract_terms(_t(type="extension", years=4), current_end=20262027)
    assert plan.values["start_season"] == 20272028 and plan.values["end_season"] == 20302031


def test_signing_with_no_terms_stores_nothing_extra():
    plan = plan_contract_terms(_t(), None)
    assert plan.values == {"contract_type": "standard"} and plan.derived == []


def test_stated_cap_hit_wins_over_arithmetic():
    plan = plan_contract_terms(_t(cap_hit=4_000_000, total_value=10_000_000, years=2), None)
    assert plan.values["cap_hit"] == 4_000_000 and plan.values["aav"] == 5_000_000


def test_same_value_compares_numbers_by_value():
    from decimal import Decimal
    assert same_value(Decimal("50.00"), 50) and not same_value(Decimal("50.00"), 25)
    assert same_value("NMC", "NMC") and not same_value(None, "NMC")


def test_schema_requires_every_field_and_allows_null():
    props = ex.TRANSACTION_SCHEMA["properties"]
    assert set(ex.TRANSACTION_SCHEMA["required"]) == set(props)
    assert {"type": "null"} in props["cap_hit"]["anyOf"]
    assert ex.TRANSACTION_SCHEMA["additionalProperties"] is False


def test_extract_reads_structured_output_and_drops_bad_item_numbers():
    payload = {"transactions": [_t(player_name="Luneau", type="extension", items=[1, 7])]}

    class FakeMessages:
        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                stop_reason="end_turn", model=kwargs["model"],
                usage=SimpleNamespace(input_tokens=900, output_tokens=120),
                content=[SimpleNamespace(type="text", text=json.dumps(payload))],
            )

    fake = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages()))
    result = ex.extract(fake, [{"title": "Ducks ink Luneau", "outlet": "NHL.com", "published_at": None}], {"ANA": "Anaheim Ducks"})
    assert result.transactions[0]["items"] == [1]  # item 7 does not exist
    sent = fake.beta.messages.kwargs
    assert sent["output_config"]["format"]["schema"] is ex.OUTPUT_SCHEMA
    assert "ANA (Anaheim Ducks)" in sent["system"]
    assert "[1] NHL.com, unknown date: Ducks ink Luneau" in sent["messages"][0]["content"]


def test_refusal_returns_no_transactions():
    class Refuse:
        def create(self, **kwargs):
            return SimpleNamespace(stop_reason="refusal", model="m", usage=SimpleNamespace(input_tokens=1, output_tokens=0), content=[])

    result = ex.extract(SimpleNamespace(beta=SimpleNamespace(messages=Refuse())), [{"title": "t"}], {})
    assert result.transactions == [] and result.stop_reason == "refusal"


def test_backfill_headline_must_name_the_player():
    from pipeline.contracts.backfill import mentions_player

    assert mentions_player("Ducks sign Cutter Gauthier to eight-year extension", "Cutter Gauthier")
    assert mentions_player("Blue Jackets sign C. Gauthier", "Cutter Gauthier")
    assert not mentions_player("Ducks sign Gauthier", "Cutter Gauthier")
    assert not mentions_player("Flyers sign Julien Gauthier", "Cutter Gauthier")
    assert mentions_player("Canadiens sign Ivan Demidov to entry-level deal", "Ivan Demidov")
