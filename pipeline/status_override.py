"""Record a player's roster status by hand, for moves the news never reported.

Usage:
    python -m pipeline.status_override "Matthew Poitras" minors --note "Per Brian: Bruins cap chart, no public assignment news"

Statuses: nhl, ir, ltir, minors, waivers. Dated today, so any later news (a recall, an injury placement) or the
nightly roster refresh replaces it as usual. The change is logged with its note.
"""

import argparse
from datetime import date

from pipeline.db import connect

STATUSES = ("nhl", "ir", "ltir", "minors", "waivers")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Set a player's roster status by hand")
    parser.add_argument("player", help="full name as on the site")
    parser.add_argument("status", choices=STATUSES)
    parser.add_argument("--note", required=True, help="where this came from")
    args = parser.parse_args(argv)
    with connect() as conn:
        rows = conn.execute(
            "select id, current_team_id from players where lower(first_name || ' ' || last_name) = lower(%s)", (args.player,)
        ).fetchall()
        if len(rows) != 1:
            raise SystemExit(f"{len(rows)} players named {args.player!r}; nothing changed.")
        player_id, team_id = rows[0]
        old = conn.execute("select status, since, source from player_status where player_id = %s", (player_id,)).fetchone()
        conn.execute(
            """insert into player_status (player_id, status, team_id, since, source, note, updated_at)
               values (%s, %s, %s, %s, 'manual', %s, now())
               on conflict (player_id) do update set status = excluded.status, since = excluded.since,
                 source = 'manual', note = excluded.note, updated_at = now()""",
            (player_id, args.status, team_id, date.today(), args.note),
        )
        conn.commit()
    print(f"{args.player}: {old[0] if old else 'none'} ({old[2] if old else '-'}) -> {args.status} (manual). Note: {args.note}")


if __name__ == "__main__":
    main()
