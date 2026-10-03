from pipeline.contracts.sourcing import compare, season_id


def test_season_id():
    assert season_id("2030-31") == 20302031 and season_id(None) is None and season_id("2030") is None


def test_compare_confirms_rounded_figures_and_flags_real_differences():
    on_file = {"cap_hit": 5_400_000, "end_season": 20302031}
    # "$43.2 million over eight years" works out to exactly 5.4M; "$5.4 million" rounded also matches.
    assert compare(on_file, [{"total_value": 43_200_000, "years": 8, "end_season": "2030-31"}])[0] == "confirmed"
    assert compare(on_file, [{"cap_hit": 5_390_000, "end_season": None}])[0] == "confirmed"
    # Same contract (same end season) with a clearly different cap hit is a mismatch.
    status, found, note = compare(on_file, [{"cap_hit": 5_900_000, "end_season": "2030-31"}])
    assert status == "mismatch" and found["cap_hit"] == 5_900_000
    # An older contract with a different end season and cap hit is not this one.
    assert compare(on_file, [{"cap_hit": 925_000, "end_season": "2022-23"}])[0] == "not_found"


def test_term_confirmed_from_length_and_date():
    from datetime import date

    from pipeline.contracts.sourcing import first_season

    # "Maple Leafs sign Brisson to one-year contract", July 2026: covers 2026-27.
    t = {"type": "signing", "years": 1, "_date": date(2026, 7, 2), "status": "completed"}
    assert first_season(t) == 20262027
    assert compare({"cap_hit": 850_000, "end_season": 20262027}, [t])[0] == "term_confirmed"
    # An extension signed in-season starts the next season.
    ext = {"type": "extension", "years": 2, "_date": date(2025, 12, 1), "status": "completed"}
    assert compare({"cap_hit": 925_000, "end_season": 20272028}, [ext])[0] == "term_confirmed"
    # A different length does not confirm anything.
    assert compare({"cap_hit": 850_000, "end_season": 20272028}, [t])[0] == "not_found"
