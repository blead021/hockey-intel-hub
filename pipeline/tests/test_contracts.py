import pytest

from pipeline.ingest.contracts import parse_money, parse_season, read_csv

HEADER = "player,team,cap_hit,aav,start_season,end_season,expiry_status,clause,no_trade_list_size,retained_pct,retained_by\n"


def test_parse_money_and_season():
    assert parse_money("$8,000,000") == 8_000_000
    assert parse_money("7750000") == 7_750_000
    assert parse_money("") is None
    assert parse_season("2025-26") == 20252026
    assert parse_season("2099-00") == 20992100
    assert parse_season("2025-2026") == parse_season("20252026") == 20252026
    with pytest.raises(ValueError):
        parse_season("2025-27")


def test_read_csv_accepts_a_good_row(tmp_path):
    path = tmp_path / "c.csv"
    path.write_text(HEADER + 'Quinn Hughes,VAN,"$7,850,000",,2021-22,2026-27,UFA,M-NTC,15,,\n', encoding="utf-8")
    [row] = read_csv(path)
    assert (row.cap_hit, row.start_season, row.end_season, row.clause, row.retained_pct) == (
        7_850_000, 20212022, 20262027, "M-NTC", 0.0)


def test_read_csv_reports_every_bad_line(tmp_path):
    path = tmp_path / "c.csv"
    path.write_text(HEADER + "A,VAN,,,2025-26,2026-27,UFA,none,,,\n" + "B,VAN,100,,2025-26,2026-27,FA,NMC,,,\n",
                    encoding="utf-8")
    with pytest.raises(ValueError) as error:
        read_csv(path)
    assert "line 2: cap_hit is empty" in str(error.value)
    assert "line 3: expiry_status must be UFA or RFA" in str(error.value)


def test_template_in_repo_has_the_right_columns():
    assert read_csv() == []
