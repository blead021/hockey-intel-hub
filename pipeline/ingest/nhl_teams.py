"""Loads the current NHL teams (id, abbreviation, name, conference, division).

Usage: python -m pipeline.ingest.nhl_teams
"""

from dataclasses import dataclass

from pipeline import archive
from pipeline.db import connect
from pipeline.http import client, get_json
from pipeline.jobs import job_run
from pipeline.sources import require_enabled

STANDINGS_URL = "https://api-web.nhle.com/v1/standings/now"
TEAMS_URL = "https://api.nhle.com/stats/rest/en/team"


class NhlSchemaError(RuntimeError):
    """The NHL API answered, but not in the shape we expect. The endpoint probably changed."""


@dataclass(frozen=True)
class Team:
    id: int
    abbrev: str
    name: str
    conference: str
    division: str


def _field(obj: dict, path: str, where: str):
    value = obj
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            raise NhlSchemaError(f"{where}: missing field {path!r}")
        value = value[key]
    return value


def parse_teams(standings: dict, team_list: dict) -> list[Team]:
    """Joins current standings (no ids) with the stats team list (ids) on the 3-letter code."""
    ids = {}
    for row in _field(team_list, "data", "team list"):
        ids[_field(row, "triCode", "team list row")] = _field(row, "id", "team list row")

    teams = []
    for row in _field(standings, "standings", "standings"):
        abbrev = _field(row, "teamAbbrev.default", "standings row")
        if abbrev not in ids:
            raise NhlSchemaError(f"standings team {abbrev} has no id in the team list")
        teams.append(
            Team(
                id=ids[abbrev],
                abbrev=abbrev,
                name=_field(row, "teamName.default", "standings row"),
                conference=_field(row, "conferenceName", "standings row"),
                division=_field(row, "divisionName", "standings row"),
            )
        )
    if len(teams) != 32:
        raise NhlSchemaError(f"expected 32 teams in standings, got {len(teams)}")
    return teams


def main() -> None:
    with job_run("nhl_teams") as counts, connect() as conn, client() as http:
        require_enabled(conn, "nhl_api")
        standings = get_json(http, STANDINGS_URL)
        team_list = get_json(http, TEAMS_URL)
        if archive.save("nhl", "standings-now", standings):
            counts["archived"] += 1
        if archive.save("nhl", "team-list", team_list):
            counts["archived"] += 1

        teams = parse_teams(standings, team_list)
        with conn.transaction():
            for t in teams:
                conn.execute(
                    """insert into teams (id, abbrev, name, conference, division, active)
                       values (%s, %s, %s, %s, %s, true)
                       on conflict (id) do update set abbrev = excluded.abbrev, name = excluded.name,
                         conference = excluded.conference, division = excluded.division, active = true""",
                    (t.id, t.abbrev, t.name, t.conference, t.division),
                )
            conn.execute("update teams set active = false where id <> all(%s)", ([t.id for t in teams],))
        counts["teams"] = len(teams)
    print(f"nhl_teams ok: {dict(counts)}")


if __name__ == "__main__":
    main()
