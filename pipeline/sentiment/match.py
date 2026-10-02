"""Finds which NHL players each mention is about, using names and context (CLAUDE.md section 4).

Usage:
    python -m pipeline.sentiment.match              mentions not matched yet
    python -m pipeline.sentiment.match --rematch    every mention (after adding aliases or nicknames)

Rules:
- A full name ("Quinn Hughes", "Q. Hughes") or a nickname from player_aliases matches with high confidence.
- A surname alone must be capitalized. If one current player has it, it matches.
- A surname shared by several players (four Hughes) is settled by context: the feed's team, team
  names in the text, and teammates named in the same mention.
- Surnames that are ordinary words (Power, Hart, Frost), someone's first name (Connor, Thomas), or a
  word in a team name (York) count only with supporting team context.
- Anything still uncertain is stored as needs_review and stays out of the scores.
Claude confirms the player when it scores the mention, so this step proposes candidates.
"""

import argparse
import re
from collections import defaultdict
from dataclasses import dataclass

from pipeline.db import connect
from pipeline.jobs import job_run

MATCHED = 0.7
BATCH = 5000
# Surnames that are also everyday words; alone they need team context.
COMMON_WORDS = {
    "power", "hart", "frost", "wood", "stone", "fox", "hall", "brown", "smith", "johnson", "miller", "walker",
    "bennett", "king", "love", "little", "young", "white", "black", "green", "long", "rich", "strong", "day",
    "post", "may", "lane", "park", "case", "bear", "price", "martin", "rice", "hughes", "lee", "jones", "kelly",
    "graves", "sharp", "wise", "page", "cross", "nash", "grant", "hunt", "steel", "booth", "carrier", "duke",
    "but", "point", "stanley",  # "But ...", "five-point night", "Stanley Cup"
}
WORD = re.compile(r"[A-Za-zÀ-ÿ'\-.]+")


@dataclass(frozen=True)
class Candidate:
    player_id: int
    confidence: float
    method: str
    status: str


class Matcher:
    def __init__(self, players: list[tuple[int, str, str, int | None]], aliases: list[tuple[int, str, str]],
                 teams: list[tuple[int, str, str]]):
        """players: (id, first, last, current team); aliases: (player id, alias, kind); teams: (id, abbrev, name)."""
        self.team_of = {pid: team for pid, _, _, team in players}
        # Surnames that are also someone's first name ("Connor" McDavid, "Thomas") or a word in a team name
        # ("York" in New York) are as risky as everyday words: they need team context too.
        first_names = {first.lower() for _, first, _, _ in players}
        team_name_words = {w.lower() for _, _, name in teams for w in name.split()}
        self.cautious = COMMON_WORDS | first_names | team_name_words
        self.by_surname: dict[str, set[int]] = defaultdict(set)
        for pid, _, last, team in players:
            if team is not None and len(last) >= 3:
                self.by_surname[last.lower()].add(pid)
        self.full: dict[str, set[int]] = defaultdict(set)
        for pid, alias, kind in aliases:
            if kind in ("name", "nickname") and (" " in alias or kind == "nickname"):
                self.full[alias.lower()].add(pid)
        self.full_pattern = self._pattern(self.full)
        # Team words: nickname ("Canucks") and city ("Vancouver"), kept only when exactly one team uses
        # the word, so "New York" (Rangers and Islanders) gives no context.
        words: dict[str, set[int]] = defaultdict(set)
        for tid, _abbrev, name in teams:
            parts = name.split()
            two_word = parts[-1] in ("Wings", "Leafs", "Jackets", "Knights")
            nickname = " ".join(parts[-2:]) if two_word else parts[-1]
            words[nickname.lower()].add(tid)
            words[name[: -len(nickname)].strip().lower()].add(tid)
        self.team_words = {w: ids for w, ids in words.items() if w and len(ids) == 1}
        self.team_pattern = self._pattern(self.team_words)

    @staticmethod
    def _pattern(index: dict) -> re.Pattern | None:
        if not index:
            return None
        names = sorted(index, key=len, reverse=True)
        return re.compile(r"(?<![\w])(" + "|".join(re.escape(n) for n in names) + r")(?![\w])", re.IGNORECASE)

    def match(self, text: str, feed_team: int | None) -> list[Candidate]:
        found: dict[int, Candidate] = {}

        def keep(c: Candidate):
            if c.player_id not in found or found[c.player_id].confidence < c.confidence:
                found[c.player_id] = c

        # 1. Full names and nicknames.
        full_players = set()
        if self.full_pattern:
            for m in self.full_pattern.finditer(text):
                ids = self.full[m.group(1).lower()]
                if len(ids) == 1:
                    pid = next(iter(ids))
                    full_players.add(pid)
                    keep(Candidate(pid, 0.95, "full_name", "matched"))
                else:
                    for pid in ids:
                        keep(Candidate(pid, 0.4, "full_name", "needs_review"))

        # 2. Context teams: the feed, team names in the text, and teams of players named in full.
        context = {feed_team} if feed_team else set()
        if self.team_pattern:
            for m in self.team_pattern.finditer(text):
                context |= self.team_words.get(m.group(1).lower(), set())
        context |= {self.team_of[p] for p in full_players if self.team_of.get(p)}

        # 3. Capitalized surnames. Unambiguous ones first, so their teams count as context for the rest
        # ("Pettersson to Hughes" points to the Vancouver Hughes).
        surnames = []
        for word in set(WORD.findall(text)):
            word = word.strip(".-'")
            if not word or not word[0].isupper():
                continue
            ids = self.by_surname.get(word.lower())
            if ids and not ids & full_players:
                surnames.append((word.lower(), ids))
        unambiguous = [(w, ids) for w, ids in surnames if len(ids) == 1 and w not in self.cautious]
        context |= {self.team_of[next(iter(ids))] for _, ids in unambiguous}

        for word, ids in surnames:
            common = word in self.cautious
            in_context = {p for p in ids if self.team_of.get(p) in context}
            if len(ids) == 1 and not common:
                pid = next(iter(ids))
                keep(Candidate(pid, 0.8 if pid in in_context else 0.7, "surname", "matched"))
            elif len(in_context) == 1:
                keep(Candidate(next(iter(in_context)), 0.75, "surname_context", "matched"))
            else:
                for pid in (in_context or ids):
                    keep(Candidate(pid, 0.3, "surname", "needs_review"))
        return list(found.values())


def load_matcher(conn) -> Matcher:
    players = conn.execute("select id, first_name, last_name, current_team_id from players").fetchall()
    aliases = conn.execute("select player_id, alias, kind from player_aliases").fetchall()
    teams = conn.execute("select id, abbrev, name from teams where active").fetchall()
    return Matcher(players, aliases, teams)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Match mentions to players")
    parser.add_argument("--rematch", action="store_true")
    args = parser.parse_args(argv)
    with job_run("mention_match") as counts, connect(autocommit=True) as conn:
        matcher = load_matcher(conn)
        if args.rematch:
            conn.execute("update mentions set matched_at = null")
        while True:
            rows = conn.execute(
                """select id, coalesce(title, '') || ' ' || coalesce(text, ''), team_id from mentions
                   where matched_at is null order by id limit %s""",
                (BATCH,),
            ).fetchall()
            if not rows:
                break
            out = []
            for mention_id, text, team in rows:
                for c in matcher.match(text, team):
                    out.append((mention_id, c.player_id, c.confidence, c.method, c.status))
                    counts[c.status] += 1
            ids = [r[0] for r in rows]
            with conn.transaction(), conn.cursor() as cur:
                # Keep anything already scored by Claude; replace only unscored matches.
                cur.execute("delete from mention_players where mention_id = any(%s) and scored_at is null", (ids,))
                cur.executemany(
                    """insert into mention_players (mention_id, player_id, confidence, match_method, status)
                       values (%s, %s, %s, %s, %s) on conflict (mention_id, player_id) do nothing""",
                    out,
                )
                cur.execute("update mentions set matched_at = now() where id = any(%s)", (ids,))
            counts["mentions"] += len(rows)
    print(f"match ok: {dict(counts)}")


if __name__ == "__main__":
    main()
