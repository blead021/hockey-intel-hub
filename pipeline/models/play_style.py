"""Writes each skater's play style text with Claude: archetype, scouting summary, tags, strengths, watch-outs.

Usage:
    python -m pipeline.models.play_style              apply finished batches, then submit stale players
    python -m pipeline.models.play_style --max 50     cap how many players one run submits (for a trial)

Runs weekly as a Message Batch (half price) on claude-haiku-4-5. Claude sees only the player's numbers
from the player_style_traits view and his season totals, never posts or articles, and is told not to
add facts that are not in them (CLAUDE.md section 6, Play style). Each player is written for the
season his profile page shows: this season once he has 100 minutes, otherwise last season.
"""

import argparse
import json
import os

from pipeline.db import connect
from pipeline.jobs import job_run
from pipeline.sources import is_enabled

MODEL = os.environ.get("PLAY_STYLE_MODEL", "claude-haiku-4-5")
REFRESH_DAYS = 6
DEFAULT_MAX = 1200

TRAITS = [
    ("p_shooting", "Shooting volume"),
    ("p_playmaking", "Playmaking"),
    ("p_entries", "Zone entries (estimate from rush chances)"),
    ("p_forecheck", "Forechecking"),
    ("p_physical", "Physicality"),
    ("p_defense", "Defensive impact"),
    ("p_puck", "Puck management"),
    ("p_speed", "Speed"),
]
GROUP_NAMES = {"C": "centers", "W": "wingers", "D": "defensemen"}
POSITION_NAMES = {"C": "center", "W": "winger", "D": "defenseman"}

SYSTEM = """You write short play style profiles of NHL skaters for a hockey analytics site.

You get one player's numbers: percentiles (0-100) versus his position group for eight traits, where he
shoots from, and season totals. Write from these numbers only. Do not mention teams, linemates, injuries,
contracts, awards, history, or anything else not in the data. Plain English for fans, no jargon, no
em dashes (use commas).

- archetype: 2 to 4 words naming his style (for example "Two-way playmaker", "Net-front shooter",
  "Shutdown defenseman", "Puck-moving defenseman").
- summary: 2 sentences describing how he plays, based on his strongest and weakest traits.
- tags: 3 to 5 short style tags (1 to 3 words each).
- strengths: 2 or 3 one-line strengths, each tied to a number given.
- watch_outs: 1 to 3 one-line weaknesses, each tied to a number given. If nothing is below the 40th
  percentile, give the lowest trait gently.
Zone entries is an estimate; say "rush chances" rather than claiming tracked zone entries."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "archetype": {"type": "string"},
        "summary": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "watch_outs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["archetype", "summary", "tags", "strengths", "watch_outs"],
    "additionalProperties": False,
}


def season_label(season: int) -> str:
    return f"{season // 10000}-{str(season % 10000)[2:]}"


def describe(p: dict) -> str:
    """The numbers Claude sees for one player."""
    group = GROUP_NAMES[p["grp"]]
    lines = [
        f"Player: {p['name']}, {POSITION_NAMES[p['grp']]}, age {p['age']}, {season_label(p['season_id'])} regular season",
        f"Totals: {p['gp']} GP, {p['g']} G, {p['a']} A, {p['g'] + p['a']} P, "
        f"{p['toi'] / 60 / p['gp']:.1f} minutes per game",
    ]
    if p.get("xgf_pct") is not None:
        lines.append(f"5v5 expected goals share while on ice: {p['xgf_pct'] * 100:.1f}%")
    if p.get("gs_pg") is not None:
        lines.append(f"Game Score: {p['gs_pg']:+.2f} goals above average per game")
    lines.append(f"Trait percentiles vs. NHL {group}:")
    for key, label in TRAITS:
        value = p.get(key)
        lines.append(f"- {label}: {'no data' if value is None else round(value * 100)}")
    total = p["slot"] + p["mid"] + p["perimeter"]
    if total:
        lines.append(
            f"Unblocked shots: {total}; slot {round(100 * p['slot'] / total)}%, "
            f"mid-range {round(100 * p['mid'] / total)}%, perimeter {round(100 * p['perimeter'] / total)}%"
        )
    return "\n".join(lines)


def clean(result: dict) -> dict:
    """Trims the model's output to the shapes the page expects; drops em dashes per the style guide."""
    def text(s, limit):
        return " ".join(str(s).replace("—", ", ").split())[:limit]

    def items(xs, n, limit):
        return [text(x, limit) for x in (xs or []) if str(x).strip()][:n]

    return {
        "archetype": text(result.get("archetype", ""), 40) or None,
        "summary": text(result.get("summary", ""), 500) or None,
        "tags": items(result.get("tags"), 5, 30),
        "strengths": items(result.get("strengths"), 3, 160),
        "watch_outs": items(result.get("watch_outs"), 3, 160),
    }


def stale_players(conn, limit: int) -> list[dict]:
    rows = conn.execute(
        """with cur as (select max(season_id) as s from games where game_type = 2),
           target as (
             select distinct on (t.player_id) t.*
             from player_style_traits t, cur
             where t.season_id >= cur.s - 10001
             order by t.player_id, t.season_id desc),
           pending as (
             select (v ->> 0)::int as player_id from play_style_batches b, jsonb_each(b.player_seasons) e(k, v)
             where b.status = 'submitted')
           select t.*, p.first_name || ' ' || p.last_name as name, date_part('year', age(p.birth_date))::int as age,
                  (select sum(o.xgf) / nullif(sum(o.xgf) + sum(o.xga), 0) from player_game_onice o
                    join games g on g.id = o.game_id
                    where o.player_id = t.player_id and g.season_id = t.season_id and g.game_type = 2)::float8 as xgf_pct,
                  (select avg(gs.game_score) from player_game_score gs join games g on g.id = gs.game_id
                    where gs.player_id = t.player_id and g.season_id = t.season_id and g.game_type = 2)::float8 as gs_pg
           from target t join players p on p.id = t.player_id
           left join player_play_style w on w.player_id = t.player_id
           where t.player_id not in (select player_id from pending)
             and (w.player_id is null or w.season_id <> t.season_id
                  or w.generated_at < now() - make_interval(days => %s))
           order by t.toi desc
           limit %s""",
        (REFRESH_DAYS, limit),
    )
    cols = [c.name for c in rows.description]
    return [dict(zip(cols, r)) for r in rows.fetchall()]


def build_request(p: dict) -> dict:
    return {
        "model": MODEL,
        "max_tokens": 800,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": describe(p)}],
        "output_config": {"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    }


def save(conn, player_id: int, season_id: int, w: dict) -> None:
    conn.execute(
        """insert into player_play_style (player_id, season_id, archetype, summary, tags, strengths, watch_outs, model, generated_at)
           values (%s, %s, %s, %s, %s, %s, %s, %s, now())
           on conflict (player_id) do update set season_id = excluded.season_id, archetype = excluded.archetype,
             summary = excluded.summary, tags = excluded.tags, strengths = excluded.strengths,
             watch_outs = excluded.watch_outs, model = excluded.model, generated_at = now()""",
        (player_id, season_id, w["archetype"], w["summary"], w["tags"], w["strengths"], w["watch_outs"], MODEL),
    )


def collect(conn, client, counts) -> None:
    for batch_id, player_seasons in conn.execute(
        "select id, player_seasons from play_style_batches where status = 'submitted' order by submitted_at"
    ).fetchall():
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status != "ended":
            counts["batches_still_running"] += 1
            continue
        tokens_in = tokens_out = 0
        for result in client.messages.batches.results(batch_id):
            pair = player_seasons.get(result.custom_id)
            if not pair or result.result.type != "succeeded":
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
                written = clean(json.loads(text))
            except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
                counts["requests_unreadable"] += 1
                continue
            save(conn, pair[0], pair[1], written)
            counts["players_written"] += 1
        conn.execute(
            """update play_style_batches set status = 'applied', applied_at = now(), input_tokens = %s,
                   output_tokens = %s where id = %s""",
            (tokens_in, tokens_out, batch_id),
        )
        counts["batches_applied"] += 1


def submit(conn, client, limit: int, counts) -> None:
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    players = stale_players(conn, limit)
    if not players:
        return
    requests = [
        Request(custom_id=f"p-{p['player_id']}", params=MessageCreateParamsNonStreaming(**build_request(p)))
        for p in players
    ]
    batch = client.messages.batches.create(requests=requests)
    conn.execute(
        "insert into play_style_batches (id, model, player_seasons, requests) values (%s, %s, %s, %s)",
        (batch.id, MODEL, json.dumps({f"p-{p['player_id']}": [p["player_id"], p["season_id"]] for p in players}),
         len(requests)),
    )
    counts["players_submitted"] = len(players)


def main(argv: list[str] | None = None) -> None:
    import anthropic

    parser = argparse.ArgumentParser(description="Write play style profiles with Claude (Message Batches)")
    parser.add_argument("--max", type=int, default=DEFAULT_MAX, help="most players to submit this run")
    args = parser.parse_args(argv)
    with job_run("play_style_writing") as counts, connect(autocommit=True) as conn:
        if not is_enabled(conn, "play_style_writing"):
            counts["switched_off"] = 1
            print("play style writing is switched off (data_sources.play_style_writing); nothing sent.")
            return
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            raise RuntimeError("ANTHROPIC_API_KEY is not set, so play styles cannot be written.")
        client = anthropic.Anthropic()
        collect(conn, client, counts)
        submit(conn, client, args.max, counts)
    print(f"play style ok: {dict(counts)}")


if __name__ == "__main__":
    main()
