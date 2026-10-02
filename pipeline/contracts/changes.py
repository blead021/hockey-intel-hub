"""Shows what the contract news job changed, and where each change came from.

Usage: python -m pipeline.contracts.changes [--days 7]
"""

import argparse

from pipeline.db import connect


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)
    with connect() as conn:
        rows = conn.execute(
            """select e.created_at, e.player_name, e.event_type, e.outcome, e.outcome_note,
                      coalesce(json_agg(json_build_object('field', c.field, 'old', c.old_value, 'new', c.new_value))
                               filter (where c.id is not null), '[]'), e.source_urls
               from contract_events e left join contract_changes c on c.event_id = e.id
               where e.created_at > now() - make_interval(days => %s)
               group by e.id order by e.created_at desc""",
            (args.days,),
        ).fetchall()
    if not rows:
        print(f"No contract news in the last {args.days} days.")
    for when, player, kind, outcome, note, changes, urls in rows:
        print(f"{when:%Y-%m-%d %H:%M}  {player}  {kind}  -> {outcome}{f' ({note})' if note else ''}")
        for c in changes:
            print(f"    {c['field']}: {c['old'] if c['old'] is not None else 'unknown'} -> {c['new']}")
        for url in urls[:3]:
            print(f"    source: {url}")


if __name__ == "__main__":
    main()
