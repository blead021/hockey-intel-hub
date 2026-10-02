"""Scores matched mentions with Claude: confirms which players each one is about, and scores sentiment.

Usage:
    python -m pipeline.sentiment.score              apply finished batches, then submit new mentions
    python -m pipeline.sentiment.score --max 2000   cap how many mentions one run submits

Runs as Message Batches (half price; results usually within an hour, at most 24). Each night the job
first applies batches that have finished, then submits mentions that have candidate players and
were never scored or sent. A mention is never sent twice (CLAUDE.md: cache by mention ID).

Per CLAUDE.md the model is small and fast (claude-haiku-4-5). Summaries are one line in the model's
own words; raw text is never copied into them.
"""

import argparse
import json
import os
from collections import defaultdict

from pipeline.db import connect
from pipeline.jobs import job_run
from pipeline.sources import is_enabled

MODEL = os.environ.get("SENTIMENT_MODEL", "claude-haiku-4-5")
MENTIONS_PER_REQUEST = 20
MAX_TEXT = 600  # characters of each mention sent to the model
DEFAULT_MAX_MENTIONS = 6000

SYSTEM = """You score hockey fan and media posts about NHL players for a hockey analytics site.

Each numbered post comes with candidate players found by name matching. For each candidate, decide:
- about: true only if the post is about that NHL player (not another person with the same name, not a
  different meaning of the word, such as "power play" or "Stanley Cup").
- sentiment: the post's attitude toward that player, from -1 (very negative) to 1 (very positive),
  0 if neutral or purely factual.
- trade: true if the post discusses trading, acquiring, waiving, or moving the player, including rumors.
- summary: if trade is true, one short line in your own words (under 15 words) about what is said;
  otherwise null. Never copy the post's wording.

Judge only the text given. Return every candidate of every post."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "post": {"type": "integer"},
                    "players": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "player_id": {"type": "integer"},
                                "about": {"type": "boolean"},
                                "sentiment": {"type": "number"},
                                "trade": {"type": "boolean"},
                                "summary": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            },
                            "required": ["player_id", "about", "sentiment", "trade", "summary"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["post", "players"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["posts"],
    "additionalProperties": False,
}


def format_request(mentions: list[dict]) -> str:
    """mentions: {id, source, audience, team, text, candidates: [(player_id, name, team)]}"""
    lines = []
    for n, m in enumerate(mentions, start=1):
        cands = "; ".join(f"{pid}: {name} ({team or 'no team'})" for pid, name, team in m["candidates"])
        text = " ".join(m["text"].split())[:MAX_TEXT]
        lines.append(f"[{n}] source: {m['source']}, {m['audience']}"
                     f"{', team feed: ' + m['team'] if m['team'] else ''}\ncandidates: {cands}\npost: {text}")
    return "\n\n".join(lines)


def build_requests(mentions: list[dict]) -> list[tuple[str, dict, list[int]]]:
    """(custom_id, params, mention ids) per group of mentions. custom_id is short (the API allows
    64 characters), so which mentions each request covers is stored with the batch."""
    out = []
    for n, start in enumerate(range(0, len(mentions), MENTIONS_PER_REQUEST)):
        group = mentions[start:start + MENTIONS_PER_REQUEST]
        custom_id = f"group-{n}"
        params = {
            "model": MODEL,
            "max_tokens": 4000,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": format_request(group)}],
            "output_config": {"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        }
        out.append((custom_id, params, [m["id"] for m in group]))
    return out


def parse_result(text: str, mention_ids: list[int], candidates: dict[int, set[int]]) -> list[dict]:
    """Turns the model's JSON into updates, ignoring post numbers or players that were not sent."""
    updates = []
    for post in json.loads(text).get("posts", []):
        n = post.get("post")
        if not isinstance(n, int) or not 1 <= n <= len(mention_ids):
            continue
        mention_id = mention_ids[n - 1]
        for p in post.get("players", []):
            if p.get("player_id") not in candidates.get(mention_id, set()):
                continue
            sentiment = max(-1.0, min(1.0, float(p.get("sentiment", 0))))
            summary = p.get("summary") if p.get("trade") else None
            updates.append({
                "mention_id": mention_id, "player_id": p["player_id"], "about": bool(p.get("about")),
                "sentiment": round(sentiment, 3), "trade": bool(p.get("trade")),
                "summary": (summary or "")[:200] or None,
            })
    return updates


def pending_mentions(conn, limit: int) -> list[dict]:
    rows = conn.execute(
        """select m.id, m.source, m.audience, t.abbrev, coalesce(m.title, '') || ' ' || coalesce(m.text, ''),
                  mp.player_id, p.first_name || ' ' || p.last_name, pt.abbrev
           from mentions m
           join mention_players mp on mp.mention_id = m.id and mp.status in ('matched', 'needs_review') and mp.scored_at is null
           join players p on p.id = mp.player_id
           left join teams t on t.id = m.team_id
           left join teams pt on pt.id = p.current_team_id
           where m.id in (
             select distinct mp2.mention_id from mention_players mp2
             where mp2.status in ('matched', 'needs_review') and mp2.scored_at is null
               and not exists (select 1 from sentiment_batches b where b.status = 'submitted' and mp2.mention_id = any(b.mention_ids))
             order by mp2.mention_id desc limit %s)
           order by m.id""",
        (limit,),
    ).fetchall()
    grouped: dict[int, dict] = {}
    for mid, source, audience, team, text, pid, name, pteam in rows:
        m = grouped.setdefault(mid, {"id": mid, "source": source, "audience": audience, "team": team, "text": text, "candidates": []})
        m["candidates"].append((pid, name, pteam))
    return list(grouped.values())


def apply_updates(conn, updates: list[dict]) -> None:
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            """update mention_players set status = case when %s then 'matched' else 'rejected' end,
                   sentiment = %s, is_trade_related = %s, summary = %s, scored_at = now(), scored_by = %s
               where mention_id = %s and player_id = %s""",
            [(u["about"], u["sentiment"], u["trade"], u["summary"], MODEL, u["mention_id"], u["player_id"]) for u in updates],
        )


def collect(conn, client, counts) -> None:
    """Applies every submitted batch that has finished."""
    for batch_id, mention_ids, groups in conn.execute(
        "select id, mention_ids, groups from sentiment_batches where status = 'submitted' order by submitted_at"
    ).fetchall():
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status != "ended":
            counts["batches_still_running"] += 1
            continue
        candidates = defaultdict(set)
        for mid, pid in conn.execute(
            "select mention_id, player_id from mention_players where mention_id = any(%s)", (mention_ids,)
        ):
            candidates[mid].add(pid)
        tokens_in = tokens_out = 0
        for result in client.messages.batches.results(batch_id):
            ids = groups.get(result.custom_id, [])
            if result.result.type != "succeeded":
                counts[f"requests_{result.result.type}"] += 1
                continue
            msg = result.result.message
            tokens_in += msg.usage.input_tokens
            tokens_out += msg.usage.output_tokens
            if msg.stop_reason in ("refusal", "max_tokens"):
                counts[f"requests_{msg.stop_reason}"] += 1
                continue
            text = next((b.text for b in msg.content if b.type == "text"), "")
            try:
                updates = parse_result(text, ids, candidates)
            except (json.JSONDecodeError, TypeError, ValueError):
                counts["requests_unreadable"] += 1
                continue
            apply_updates(conn, updates)
            counts["players_scored"] += len(updates)
        conn.execute(
            """update sentiment_batches set status = 'applied', applied_at = now(), input_tokens = %s, output_tokens = %s
               where id = %s""",
            (tokens_in, tokens_out, batch_id),
        )
        counts["batches_applied"] += 1


def submit(conn, client, limit: int, counts) -> None:
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    mentions = pending_mentions(conn, limit)
    if not mentions:
        return
    built = build_requests(mentions)
    requests = [Request(custom_id=cid, params=MessageCreateParamsNonStreaming(**params)) for cid, params, _ids in built]
    batch = client.messages.batches.create(requests=requests)
    conn.execute(
        "insert into sentiment_batches (id, model, mention_ids, groups, requests) values (%s, %s, %s, %s, %s)",
        (batch.id, MODEL, [m["id"] for m in mentions], json.dumps({cid: ids for cid, _p, ids in built}), len(requests)),
    )
    counts["mentions_submitted"] = len(mentions)
    counts["requests_submitted"] = len(requests)


def main(argv: list[str] | None = None) -> None:
    import anthropic

    parser = argparse.ArgumentParser(description="Score mentions with Claude (Message Batches)")
    parser.add_argument("--max", type=int, default=DEFAULT_MAX_MENTIONS, help="most mentions to submit this run")
    args = parser.parse_args(argv)
    with job_run("sentiment_score") as counts, connect(autocommit=True) as conn:
        if not is_enabled(conn, "sentiment_scoring"):
            counts["switched_off"] = 1
            print("sentiment scoring is switched off (data_sources.sentiment_scoring); nothing sent.")
            return
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            raise RuntimeError("ANTHROPIC_API_KEY is not set, so mentions cannot be scored.")
        client = anthropic.Anthropic()
        collect(conn, client, counts)
        submit(conn, client, args.max, counts)
    print(f"sentiment score ok: {dict(counts)}")


if __name__ == "__main__":
    main()
