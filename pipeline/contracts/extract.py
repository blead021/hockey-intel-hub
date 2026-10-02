"""Uses Claude to turn contract news headlines into structured transactions.

Claude only reads what the headlines and summaries say. Anything not stated comes back as null,
and the update rules (apply.py) treat null as "keep what is on file" or "unknown".
"""

import json
import os
from dataclasses import dataclass

import anthropic

MODEL = os.environ.get("CONTRACTS_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("CONTRACTS_EFFORT", "medium")
BATCH_SIZE = 40

EVENT_TYPES = ["signing", "extension", "entry_level", "trade", "waiver_claim", "buyout", "termination", "other"]


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


TRANSACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": EVENT_TYPES},
        "status": {"type": "string", "enum": ["completed", "reported", "rumor"]},
        "player_name": {"type": "string"},
        "team": _nullable({"type": "string"}),
        "from_team": _nullable({"type": "string"}),
        "cap_hit": _nullable({"type": "integer"}),
        "total_value": _nullable({"type": "integer"}),
        "years": _nullable({"type": "integer"}),
        "start_season": _nullable({"type": "string"}),
        "end_season": _nullable({"type": "string"}),
        "expiry_status": _nullable({"type": "string", "enum": ["UFA", "RFA"]}),
        "clause": _nullable({"type": "string", "enum": ["NMC", "NTC", "M-NTC", "none"]}),
        "no_trade_list_size": _nullable({"type": "integer"}),
        "retained_pct": _nullable({"type": "number"}),
        "retained_by": _nullable({"type": "string"}),
        "items": {"type": "array", "items": {"type": "integer"}},
        "evidence": {"type": "string"},
    },
    "required": [
        "type", "status", "player_name", "team", "from_team", "cap_hit", "total_value", "years",
        "start_season", "end_season", "expiry_status", "clause", "no_trade_list_size", "retained_pct",
        "retained_by", "items", "evidence",
    ],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"transactions": {"type": "array", "items": TRANSACTION_SCHEMA}},
    "required": ["transactions"],
    "additionalProperties": False,
}


def system_prompt(team_codes: dict[str, str]) -> str:
    codes = ", ".join(f"{code} ({name})" for code, name in sorted(team_codes.items()))
    return f"""You extract NHL contract transactions from news headlines for a hockey analytics site's contract records. The records feed cap math shown to fans, so a wrong number is worse than a missing one.

You will get numbered news items: outlet, date, and headline (sometimes a short summary). Return one transaction per player per transaction. When several items describe the same transaction, return it once and list every item number in "items".

Fields:
- type: signing (a new contract that is not an extension or entry-level deal, including re-signing a pending free agent), extension (signed while a current contract still has time left), entry_level, trade, waiver_claim, buyout, termination, or other (anything else, such as a player placed on waivers, an AHL-only deal, a professional tryout, or a coaching move).
- status: completed when the team or league announced it or the item reports it as done ("signs", "acquired", "claimed"). reported when it is attributed to sources or insiders ("reportedly", "per sources", "is expected to", "agreed to terms, according to"). rumor for speculation or talks.
- player_name: the player's full name as written.
- team: the team the player is now under contract with (signing team, acquiring team, or claiming team). from_team: the team he left, for trades and waiver claims. Use these codes only: {codes}.
- cap_hit, total_value: whole US dollars ("$43.2 million" is 43200000). years: contract length in seasons.
- start_season, end_season: like "2027-28", only when stated (for example "runs through 2030-31" gives end_season "2030-31").
- expiry_status, clause, no_trade_list_size: only when stated. clause "none" only when the item says there is no clause.
- retained_pct and retained_by: for trades where a team keeps part of the salary ("retain 50 percent" is 50).
- evidence: a short paraphrase, in your own words, of what the items say. Under 20 words. Do not copy sentences.

Rules:
- Use only what the items state. Never fill a field from memory or general knowledge, and never calculate one field from another. Use null for anything not stated.
- Skip items that are not about a player transaction. A list with no transactions is a valid answer.
- For a trade involving several players, return one transaction per player, all of type trade."""


@dataclass
class Extraction:
    transactions: list[dict]
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str


def format_items(items: list[dict]) -> str:
    lines = []
    for n, item in enumerate(items, start=1):
        date = item["published_at"].strftime("%Y-%m-%d") if item.get("published_at") else "unknown date"
        lines.append(f"[{n}] {item.get('outlet') or 'unknown outlet'}, {date}: {item['title']}")
    return "\n".join(lines)


def extract(client: anthropic.Anthropic, items: list[dict], team_codes: dict[str, str]) -> Extraction:
    """One request for up to BATCH_SIZE items. Item numbers in the result are 1-based positions in items."""
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=system_prompt(team_codes),
        messages=[{"role": "user", "content": "News items:\n" + format_items(items)}],
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        # If a safety classifier declines, the request is retried on a fallback model in the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    usage = response.usage
    if response.stop_reason == "refusal":
        return Extraction([], response.model, usage.input_tokens, usage.output_tokens, "refusal")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("contract extraction was cut off at max_tokens; lower BATCH_SIZE")
    text = next(b.text for b in response.content if b.type == "text")
    transactions = json.loads(text)["transactions"]
    for t in transactions:
        t["items"] = [i for i in t["items"] if 1 <= i <= len(items)]
    return Extraction(transactions, response.model, usage.input_tokens, usage.output_tokens, response.stop_reason)
