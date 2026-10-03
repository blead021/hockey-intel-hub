"""Players: current rosters, names from game rosters, and birth dates for anyone still missing one."""

from pipeline.ingest import nhl
from pipeline.ingest.nhl import PlayerInfo


def upsert_players(conn, players: list[PlayerInfo], set_current_team: bool = False) -> None:
    """Adds or updates players. Known details are never overwritten with blanks.

    Only current rosters set current_team_id; old games must not move a player back to a past team.
    """
    with conn.cursor() as cur:
        cur.executemany(
            f"""insert into players (id, first_name, last_name, position, current_team_id, sweater_number,
                   headshot_url, birth_date, shoots, height_in, weight_lb, birth_city, birth_country, updated_at)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
               on conflict (id) do update set
                 first_name = excluded.first_name,
                 last_name = excluded.last_name,
                 position = coalesce(excluded.position, players.position),
                 {"current_team_id = excluded.current_team_id," if set_current_team else ""}
                 sweater_number = coalesce(excluded.sweater_number, players.sweater_number),
                 headshot_url = coalesce(excluded.headshot_url, players.headshot_url),
                 birth_date = coalesce(excluded.birth_date, players.birth_date),
                 shoots = coalesce(excluded.shoots, players.shoots),
                 height_in = coalesce(excluded.height_in, players.height_in),
                 weight_lb = coalesce(excluded.weight_lb, players.weight_lb),
                 birth_city = coalesce(excluded.birth_city, players.birth_city),
                 birth_country = coalesce(excluded.birth_country, players.birth_country),
                 updated_at = now()""",
            [
                (
                    p.id, p.first_name, p.last_name, p.position,
                    p.team_id if set_current_team else None,
                    p.sweater_number, p.headshot_url, p.birth_date, p.shoots,
                    p.height_in, p.weight_lb, p.birth_city, p.birth_country,
                )
                for p in players
            ],
        )
        # Name aliases for matching mentions later: "Quinn Hughes" and "Q. Hughes".
        cur.executemany(
            """insert into player_aliases (player_id, alias, kind, source)
               values (%s, %s, 'name', 'any') on conflict do nothing""",
            [
                (p.id, alias)
                for p in players
                for alias in (f"{p.first_name} {p.last_name}", f"{p.first_name[:1]}. {p.last_name}")
            ],
        )


def refresh_rosters(conn, http, counts) -> None:
    """Loads all 32 current rosters and clears the team of anyone no longer on one."""
    teams = conn.execute("select id, abbrev from teams where active order by abbrev").fetchall()
    on_roster: set[int] = set()
    for team_id, abbrev in teams:
        players = nhl.parse_roster(nhl.roster(http, abbrev), team_id)
        with conn.transaction():
            upsert_players(conn, players, set_current_team=True)
        on_roster |= {p.id for p in players}
        counts["roster_players"] += len(players)
    with conn.transaction():
        # Everyone on an NHL roster is up with the big club, unless news from today already says otherwise.
        conn.execute(
            """insert into player_status (player_id, status, team_id, since)
               select p.id, 'nhl', p.current_team_id, current_date from players p where p.id = any(%s)
               on conflict (player_id) do update set status = 'nhl', team_id = excluded.team_id,
                 since = current_date, source = 'roster', note = null, cap_charge = null, updated_at = now()
               where player_status.status <> 'nhl' and player_status.since < current_date""",
            (list(on_roster),),
        )
        counts["left_rosters"] = conn.execute(
            "update players set current_team_id = null, updated_at = now() "
            "where current_team_id is not null and id <> all(%s)",
            (list(on_roster),),
        ).rowcount


def refresh_prospects(conn, http, counts) -> None:
    """Loads each team's prospect list (players whose NHL rights a team holds, outside its NHL roster) and
    records the team in rights_team_id. Anyone no longer listed has rights_team_id cleared."""
    teams = conn.execute("select id, abbrev from teams where active order by abbrev").fetchall()
    listed: set[int] = set()
    for team_id, abbrev in teams:
        players = nhl.parse_roster(nhl.get_json(http, f"{nhl.WEB}/prospects/{abbrev}"), team_id)
        with conn.transaction():
            upsert_players(conn, players)
            conn.execute("update players set rights_team_id = %s where id = any(%s)", (team_id, [p.id for p in players]))
        listed |= {p.id for p in players}
        counts["prospects"] += len(players)
    with conn.transaction():
        conn.execute(
            "update players set rights_team_id = null where rights_team_id is not null and id <> all(%s)", (list(listed),)
        )


def fill_missing_bios(conn, http, counts, limit: int = 500) -> None:
    """Players first seen in old games have no birth date or size yet; fetch their profile pages."""
    ids = [r[0] for r in conn.execute("select id from players where birth_date is null order by id limit %s", (limit,))]
    for player_id in ids:
        info = nhl.parse_landing(nhl.player_landing(http, player_id))
        # Keep current_team_id as-is: the landing page's team can lag behind trades.
        with conn.transaction():
            upsert_players(conn, [info])
        counts["bios_filled"] += 1
