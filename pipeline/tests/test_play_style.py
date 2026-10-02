from pipeline.models.play_style import build_request, clean, describe

PLAYER = {
    "player_id": 1, "season_id": 20252026, "grp": "C", "name": "Test Center", "age": 27, "gp": 80, "g": 30, "a": 40,
    "toi": 80 * 18 * 60, "xgf_pct": 0.534, "gs_pg": 0.21, "slot": 60, "mid": 30, "perimeter": 10,
    "p_shooting": 0.9, "p_playmaking": 0.75, "p_entries": None, "p_forecheck": 0.2, "p_physical": 0.1,
    "p_defense": 0.5, "p_puck": 0.66, "p_speed": 0.88,
}


def test_describe_lists_numbers_only():
    text = describe(PLAYER)
    assert "Test Center, center, age 27, 2025-26 regular season" in text
    assert "80 GP, 30 G, 40 A, 70 P, 18.0 minutes per game" in text
    assert "- Shooting volume: 90" in text and "- Zone entries (estimate from rush chances): no data" in text
    assert "slot 60%, mid-range 30%, perimeter 10%" in text
    assert "53.4%" in text and "+0.21" in text


def test_build_request_uses_structured_output():
    req = build_request(PLAYER)
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert req["messages"][0]["content"] == describe(PLAYER)


def test_clean_trims_and_removes_em_dashes():
    out = clean({"archetype": "Sniper — pure", "summary": "  Shoots   a lot. ", "tags": ["a", "", "b", "c", "d", "e", "f"],
                 "strengths": ["x"] * 5, "watch_outs": []})
    assert out["archetype"] == "Sniper , pure"
    assert out["summary"] == "Shoots a lot."
    assert out["tags"] == ["a", "b", "c", "d", "e"] and len(out["strengths"]) == 3 and out["watch_outs"] == []
