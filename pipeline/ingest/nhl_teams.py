"""Loads the current NHL teams (id, abbreviation, name, conference, division).

Usage: python -m pipeline.ingest.nhl_teams

Teams that no longer exist (such as the Arizona Coyotes) are added as inactive when an older
game refers to them, through ensure_teams().
"""

from dataclasses import dataclass

from pipeline import archive
from pipeline.db import connect
from pipeline.http import client, get_json
from pipeline.ingest.nhl import STATS, WEB, NhlSchemaError, field
from pipeline.jobs import job_run
from pipeline.sources import require_enabled

STANDINGS_URL = f"{WEB}/standings/now"
TEAMS_URL = f"{STATS}/team"


@dataclass(frozen=True)
class Team:
    id: int
    abbrev: str
    name: str
    conference: str
    division: str


def parse_teams(standings: dict, team_list: dict) -> list[Team]:
    """Joins current standings (no ids) with the stats team list (ids) on the 3-letter code."""
    # Several teams can share a code over the years (Utah Hockey Club and Utah Mammoth are both
    # UTA), so match on code and full name together.
    by_code: dict[str, list[dict]] = {}
    for row in field(team_list, "data", "team list"):
        by_code.setdefault(field(row, "triCode", "team list row"), []).append(row)

    teams = []
    for row in field(standings, "standings", "standings"):
        abbrev = field(row, "teamAbbrev.default", "standings row")
        name = field(row, "teamName.default", "standings row")
        candidates = by_code.get(abbrev, [])
        matches = [c for c in candidates if c.get("fullName") == name] or (candidates if len(candidates) == 1 else [])
        if len(matches) != 1:
            raise NhlSchemaError(f"cannot pick one team id for {abbrev} {name!r} from the team list")
        teams.append(
            Team(
                id=field(matches[0], "id", "team list row"),
                abbrev=abbrev,
                name=name,
                conference=field(row, "conferenceName", "standings row"),
                division=field(row, "divisionName", "standings row"),
            )
        )
    if len(teams) != 32:
        raise NhlSchemaError(f"expected 32 teams in standings, got {len(teams)}")
    return teams


def refresh(conn, http, counts) -> None:
    standings = get_json(http, STANDINGS_URL)
    team_list = get_json(http, TEAMS_URL)
    archive.save("nhl", "standings-now", standings)
    archive.save("nhl", "team-list", team_list)

    teams = parse_teams(standings, team_list)
    with conn.transaction():
        # Deactivate first, so a team that took over another's code (a relocation or rename) fits.
        conn.execute("update teams set active = false where id <> all(%s)", ([t.id for t in teams],))
        for t in teams:
            conn.execute(
                """insert into teams (id, abbrev, name, conference, division, active)
                   values (%s, %s, %s, %s, %s, true)
                   on conflict (id) do update set abbrev = excluded.abbrev, name = excluded.name,
                     conference = excluded.conference, division = excluded.division, active = true""",
                (t.id, t.abbrev, t.name, t.conference, t.division),
            )
    counts["teams"] = len(teams)


def ensure_teams(conn, http, team_ids: set[int]) -> int:
    """Adds any team ids we have not seen, as inactive teams, from the NHL's full team list."""
    known = {row[0] for row in conn.execute("select id from teams")}
    missing = team_ids - known
    if not missing:
        return 0
    rows = {row["id"]: row for row in field(get_json(http, TEAMS_URL), "data", "team list")}
    for team_id in missing:
        if team_id not in rows:
            raise NhlSchemaError(f"team {team_id} appears in a game but not in the NHL team list")
        row = rows[team_id]
        conn.execute(
            "insert into teams (id, abbrev, name, active) values (%s, %s, %s, false) on conflict (id) do nothing",
            (team_id, row["triCode"], row["fullName"]),
        )
    return len(missing)


def main() -> None:
    with job_run("nhl_teams") as counts, connect() as conn, client() as http:
        require_enabled(conn, "nhl_api")
        refresh(conn, http, counts)
    print(f"nhl_teams ok: {dict(counts)}")


if __name__ == "__main__":
    main()
