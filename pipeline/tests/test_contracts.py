import pytest
from openpyxl import Workbook

from pipeline.ingest.contracts import COLUMNS, XLSX_PATH, parse_money, parse_record, parse_season, read_csv, read_file

HEADER = ",".join(COLUMNS) + "\n"


def _rec(**values):
    return {c: values.get(c, "") for c in COLUMNS}


def test_parse_money_and_season():
    assert parse_money("$8,000,000") == 8_000_000
    assert parse_money("7750000") == 7_750_000
    assert parse_money(7850000.0) == 7_850_000  # Excel numbers
    assert parse_money("7.85M") == 7_850_000
    assert parse_money("") is None and parse_money("unknown") is None
    assert parse_season("2025-26") == 20252026
    assert parse_season("2099-00") == 20992100
    assert parse_season("2025-2026") == parse_season("20252026") == 20252026
    assert parse_season("Unknown") is None
    with pytest.raises(ValueError):
        parse_season("2025-27")


def test_good_row_and_unknown_optional_fields():
    row, problems = parse_record(2, _rec(player="Quinn Hughes", team="van", cap_hit="$7,850,000",
                                         start_season="2021-22", end_season="2026-27", expiry_status="UFA",
                                         clause="unknown", no_trade_list_size=15.0))
    assert problems == []
    assert (row.team, row.cap_hit, row.start_season, row.end_season) == ("VAN", 7_850_000, 20212022, 20262027)
    assert row.clause is None  # "unknown" is stored as unknown, not guessed
    assert row.no_trade_list_size == 15
    assert row.retained_pct == 0.0


def test_missing_required_field_is_reported_but_row_is_kept_with_unknowns():
    row, problems = parse_record(3, _rec(player="A Player", team="VAN", start_season="2025-26"))
    assert row is not None and row.cap_hit is None and row.end_season is None
    assert "cap_hit is missing" in problems
    assert "end_season is missing" in problems


def test_row_without_player_or_team_cannot_be_kept():
    row, problems = parse_record(4, _rec(cap_hit="1000000", start_season="2025-26", end_season="2026-27"))
    assert row is None
    assert "player is missing" in problems and "team is missing" in problems


def test_bad_values_are_reported_and_stored_as_unknown():
    row, problems = parse_record(5, _rec(player="B", team="VAN", cap_hit="lots", start_season="2025-26",
                                         end_season="2026-27", expiry_status="FA", retained_pct="75"))
    assert row.cap_hit is None and row.retained_pct is None
    assert any("not a dollar amount" in p for p in problems)
    assert any("expiry_status must be UFA or RFA" in p for p in problems)
    assert any("between 0 and 50" in p for p in problems)


def test_read_file_from_xlsx_reports_row_numbers(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "contracts"
    ws.append(COLUMNS)
    ws.append(["Quinn Hughes", "VAN", 7850000, None, "2021-22", "2026-27", "UFA", "M-NTC", 15, None, None])
    ws.append([None] * len(COLUMNS))  # blank rows are ignored
    ws.append(["Elias Pettersson", "VAN", None, None, "2024-25", "2031-32", None, None, None, None, None])
    path = tmp_path / "c.xlsx"
    wb.save(path)
    result = read_file(path)
    assert [r.player for r in result.rows] == ["Quinn Hughes", "Elias Pettersson"]
    assert result.problems == [(4, "Elias Pettersson", "cap_hit is missing")]


def test_strict_csv_reader_raises_with_line_numbers(tmp_path):
    path = tmp_path / "c.csv"
    path.write_text(HEADER + "A,VAN,,,2025-26,2026-27,UFA,none,,,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2: cap_hit is missing"):
        read_csv(path)


def test_template_in_repo_has_the_right_columns():
    assert XLSX_PATH.exists()
    read_file(XLSX_PATH)  # raises if a column is missing
