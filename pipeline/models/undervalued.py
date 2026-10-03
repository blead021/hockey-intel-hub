"""One-line reasons for undervalued players (CLAUDE.md section 6, perception gap), written by Claude.

Usage:
    python -m pipeline.models.undervalued

Candidates: the league's 10 biggest perception gaps and each team's top 4 (the League page and the roster's
"Undervalued on this roster"), from the player_perception view: performance percentile 60+, household
names left out. Claude sees only the player's numbers, never posts or articles, and writes one plain line in
its own words. Runs nightly on Sonnet, 20 players per request (about 5 cents a night). Behind the
sentiment_scoring switch, since it needs fan scores and the same Claude key.
"""

import json
import os

from pipeline.claude import client as claude_client
from pipeline.db import connect
from pipeline.jobs import job_run
from pipeline.sources import is_enabled

MODEL = os.environ.get("UNDERVALUED_MODEL", "claude-sonnet-5-5")  # about 5 cents a night; the small model exaggerated
PER_REQUEST = 20

SYSTEM = """You write one-line explanations for a hockey analytics site's "undervalued" lists: players whose
on-ice performance ranks well above how their own fans currently feel about them.

For each numbered player you get his numbers. Write one line, under 14 words, in plain fan language, making
ONE point about what fans may be missing. Good examples: "Strong 5v5 defense hidden behind modest point totals";
"His line keeps winning the shot battle, but pucks are not going in"; "Steady starter quietly saving goals above
expected". At most one number, and only if it makes the point clearer. Do not mention percentiles or WAR. Use
only what the numbers show; never describe age, style, role, injuries, or linemates. No em dashes. Return
every player."""

SCHEMA = {
    "type": "object",
    "properties": {"players": {"type": "array", "items": {
        "type": "object",
        "properties": {"n": {"type": "integer"}, "reason": {"type": "string"}},
        "required": ["n", "reason"], "additionalProperties": False}}},
    "required": ["players"], "additionalProperties": False,
}


def candidates(conn) -> list[dict]:
    rows = conn.execute(
        """with c as (
             select x.*, p.first_name || ' ' || p.last_name as name, t.abbrev as team, p.position,
                    row_number() over (partition by p.current_team_id order by x.gap desc) as team_rank,
                    row_number() over (order by x.gap desc) as league_rank
             from player_perception x join players p on p.id = x.player_id join teams t on t.id = p.current_team_id
             where not x.star and x.perf_pct >= 60 and x.gap > 0)
           select c.*, b.pdo, b.gf_pct, b.results_pct, b.underlying_pct
           from c left join player_buy_low b on b.player_id = c.player_id
           where c.team_rank <= 4 or c.league_rank <= 10"""
    )
    cols = [d.name for d in rows.description]
    return [dict(zip(cols, r)) for r in rows.fetchall()]


def describe(n: int, c: dict) -> str:
    bits = [f"[{n}] {c['name']}, {c['position']}, {c['team']}",
            f"fan sentiment {round(c['fans'])}/100 (fans rank him {round(c['fans_pct'])}th percentile at his position)",
            f"performance {round(c['perf_pct'])}th percentile"]
    if c.get("xgf_pct") is not None:
        bits.append(f"5v5 expected goals share {c['xgf_pct'] * 100:.1f}%")
    if c.get("gf_pct") is not None:
        bits.append(f"5v5 actual goals share {c['gf_pct'] * 100:.1f}%")
    if c.get("war_proj") is not None:
        bits.append(f"projected WAR per 82 {c['war_proj']:.1f}")
    if c.get("gs_pg") is not None:
        bits.append(f"Game Score {c['gs_pg']:+.2f} goals above average per game")
    if c.get("pdo") is not None:
        bits.append(f"on-ice PDO {c['pdo']:.1f} (100 is average luck)")
    if c.get("results_pct") is not None and c.get("underlying_pct") is not None:
        bits.append(f"results {round(c['results_pct'])}th percentile vs underlying play {round(c['underlying_pct'])}th")
    return "; ".join(bits)


def main() -> None:
    with job_run("undervalued_reasons") as counts, connect(autocommit=True) as conn:
        if not is_enabled(conn, "sentiment_scoring"):
            counts["switched_off"] = 1
            print("undervalued reasons: sentiment scoring is switched off; nothing sent.")
            return
        people = candidates(conn)
        claude = claude_client()
        for start in range(0, len(people), PER_REQUEST):
            group = people[start:start + PER_REQUEST]
            response = claude.messages.create(
                model=MODEL, max_tokens=12000, system=SYSTEM,
                messages=[{"role": "user", "content": "\n".join(describe(i + 1, c) for i, c in enumerate(group))}],
                output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            )
            counts["input_tokens"] += response.usage.input_tokens
            counts["output_tokens"] += response.usage.output_tokens
            if response.stop_reason in ("max_tokens", "refusal"):
                counts[f"requests_{response.stop_reason}"] += 1
                continue
            text = next((b.text for b in response.content if b.type == "text"), "{}")
            try:
                items = json.loads(text).get("players", [])
            except json.JSONDecodeError:
                counts["requests_unreadable"] += 1
                continue
            for item in items:
                n = item.get("n")
                if isinstance(n, int) and 1 <= n <= len(group):
                    reason = " ".join(str(item.get("reason", "")).replace("—", ", ").split())[:160]
                    conn.execute(
                        """insert into player_value_reasons (player_id, reason, model, generated_at)
                           values (%s, %s, %s, now())
                           on conflict (player_id) do update set reason = excluded.reason, model = excluded.model,
                             generated_at = now()""",
                        (group[n - 1]["player_id"], reason, MODEL),
                    )
                    counts["reasons"] += 1
    print(f"undervalued reasons ok: {dict(counts)}")


if __name__ == "__main__":
    main()
