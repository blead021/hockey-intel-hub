import json

from pipeline.sentiment.score import MENTIONS_PER_REQUEST, OUTPUT_SCHEMA, build_requests, format_request, parse_result


def mention(i, candidates=((1, "Quinn Hughes", "VAN"),)):
    return {"id": i, "source": "bluesky", "audience": "fan", "team": "VAN", "text": f"post {i}  with   spaces",
            "candidates": list(candidates)}


def test_requests_group_mentions_with_short_ids():
    built = build_requests([mention(i) for i in range(1, 46)])
    assert [len(ids) for _cid, _p, ids in built] == [MENTIONS_PER_REQUEST, MENTIONS_PER_REQUEST, 5]
    assert all(len(cid) <= 64 for cid, _p, _ids in built)
    params = built[0][1]
    assert params["model"] == "claude-haiku-4-5" and "effort" not in params.get("output_config", {})
    assert params["output_config"]["format"]["schema"] is OUTPUT_SCHEMA


def test_format_request_numbers_posts_and_lists_candidates():
    text = format_request([mention(7, [(1, "Quinn Hughes", "VAN"), (2, "Jack Hughes", "NJD")])])
    assert text.startswith("[1] source: bluesky, fan, team feed: VAN")
    assert "candidates: 1: Quinn Hughes (VAN); 2: Jack Hughes (NJD)" in text
    assert "post: post 7 with spaces" in text


def test_parse_result_maps_posts_and_ignores_unknowns():
    payload = {"posts": [
        {"post": 1, "players": [
            {"player_id": 1, "about": True, "sentiment": 1.7, "trade": True, "summary": "Linked to a deal"},
            {"player_id": 99, "about": True, "sentiment": 0.5, "trade": False, "summary": None},   # not a candidate
        ]},
        {"post": 2, "players": [{"player_id": 2, "about": False, "sentiment": 0, "trade": False, "summary": "x"}]},
        {"post": 9, "players": [{"player_id": 1, "about": True, "sentiment": 0, "trade": False, "summary": None}]},  # no such post
    ]}
    updates = parse_result(json.dumps(payload), [101, 102], {101: {1}, 102: {2}})
    assert updates == [
        {"mention_id": 101, "player_id": 1, "about": True, "sentiment": 1.0, "trade": True, "summary": "Linked to a deal"},
        {"mention_id": 102, "player_id": 2, "about": False, "sentiment": 0.0, "trade": False, "summary": None},
    ]
