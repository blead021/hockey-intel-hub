"""The single client for the NHL's unofficial APIs, plus parsers that check each response's shape.

The endpoints are undocumented and change without notice. Every field read goes through `field()`,
so a changed response fails with a message naming the missing field instead of storing bad data.
Endpoints are listed in pipeline/ingest/README.md.
"""

from dataclasses import dataclass
from datetime import date

from pipeline.http import get_json

WEB = "https://api-web.nhle.com/v1"
STATS = "https://api.nhle.com/stats/rest/en"
GAME_TYPES = {2, 3}  # regular season and playoffs; preseason (1) and all-star games are skipped
FINAL_STATES = {"OFF", "FINAL"}


class NhlSchemaError(RuntimeError):
    """The NHL API answered, but not in the shape we expect. The endpoint probably changed."""


def field(obj, path: str, where: str):
    value = obj
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            raise NhlSchemaError(f"{where}: missing field {path!r}")
        value = value[key]
    return value


def toi_seconds(value: str | None) -> int:
    """Converts "MM:SS" (minutes may exceed 59) to seconds."""
    if not value:
        return 0
    minutes, seconds = value.split(":")
    return int(minutes) * 60 + int(seconds)


# --- fetching ---------------------------------------------------------------------------------


def club_season_schedule(http, team: str, season: int) -> dict:
    return get_json(http, f"{WEB}/club-schedule-season/{team}/{season}")


def boxscore(http, game_id: int) -> dict:
    return get_json(http, f"{WEB}/gamecenter/{game_id}/boxscore")


def play_by_play(http, game_id: int) -> dict:
    return get_json(http, f"{WEB}/gamecenter/{game_id}/play-by-play")


def shift_chart(http, game_id: int) -> dict:
    return get_json(http, f"{STATS}/shiftcharts", params={"cayenneExp": f"gameId={game_id}"})


def roster(http, team: str, season: int | None = None) -> dict:
    return get_json(http, f"{WEB}/roster/{team}/{season or 'current'}")


def player_landing(http, player_id: int) -> dict:
    return get_json(http, f"{WEB}/player/{player_id}/landing")


def time_on_ice_report(http, start: date, end: date) -> list[dict]:
    """Per-player, per-game even strength, power play, and shorthanded ice time for a date range."""
    expression = f'gameDate>="{start.isoformat()}" and gameDate<="{end.isoformat()}" and gameTypeId in (2,3)'
    body = get_json(
        http,
        f"{STATS}/skater/timeonice",
        params={"isAggregate": "false", "isGame": "true", "start": 0, "limit": -1, "cayenneExp": expression},
    )
    rows = field(body, "data", "time on ice report")
    if len(rows) != field(body, "total", "time on ice report"):
        raise NhlSchemaError("time on ice report returned fewer rows than its total; paging may have changed")
    return rows


def edge_skater(http, player_id: int, season: int, game_type: int = 2) -> dict:
    return get_json(http, f"{WEB}/edge/skater-detail/{player_id}/{season}/{game_type}")


# --- parsing ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class GameRow:
    id: int
    season_id: int
    game_type: int
    game_date: str
    start_time_utc: str | None
    home_team_id: int
    away_team_id: int
    home_score: int | None
    away_score: int | None
    state: str
    venue: str | None
    last_period_type: str | None


def parse_club_schedule(body: dict) -> list[GameRow]:
    games = []
    for g in field(body, "games", "club schedule"):
        game_type = field(g, "gameType", "club schedule game")
        if game_type not in GAME_TYPES:
            continue
        games.append(
            GameRow(
                id=field(g, "id", "club schedule game"),
                season_id=field(g, "season", "club schedule game"),
                game_type=game_type,
                game_date=field(g, "gameDate", "club schedule game"),
                start_time_utc=g.get("startTimeUTC"),
                home_team_id=field(g, "homeTeam.id", "club schedule game"),
                away_team_id=field(g, "awayTeam.id", "club schedule game"),
                home_score=g["homeTeam"].get("score"),
                away_score=g["awayTeam"].get("score"),
                state=field(g, "gameState", "club schedule game"),
                venue=(g.get("venue") or {}).get("default"),
                last_period_type=(g.get("gameOutcome") or {}).get("lastPeriodType"),
            )
        )
    return games


@dataclass
class SkaterLine:
    player_id: int
    team_id: int
    position: str
    g: int
    assists: int  # boxscore total, used to check the A1/A2 split from play-by-play
    sog: int
    hits: int
    blocks: int
    pim: int
    plus_minus: int
    giveaways: int
    takeaways: int
    shifts: int | None
    toi_sec: int
    a1: int = 0
    a2: int = 0
    fow: int = 0
    fol: int = 0


@dataclass
class GoalieLine:
    player_id: int
    team_id: int
    started: bool
    decision: str | None
    shots_against: int
    saves: int
    ga: int
    ev_shots_against: int | None
    ev_ga: int | None
    pp_shots_against: int | None
    pp_ga: int | None
    sh_shots_against: int | None
    sh_ga: int | None
    toi_sec: int


def _split(value: str | None) -> tuple[int | None, int | None]:
    """Boxscore goalie splits look like "22/24" (saves/shots). Returns (shots, goals against)."""
    if not value or "/" not in value:
        return None, None
    saves, shots = (int(x) for x in value.split("/"))
    return shots, shots - saves


def parse_boxscore(box: dict) -> tuple[list[SkaterLine], list[GoalieLine]]:
    skaters, goalies = [], []
    stats = field(box, "playerByGameStats", "boxscore")
    for side in ("awayTeam", "homeTeam"):
        team_id = field(box, f"{side}.id", "boxscore")
        team = field(stats, side, "boxscore player stats")
        for group in ("forwards", "defense"):
            for p in field(team, group, f"boxscore {side}"):
                where = f"boxscore skater {p.get('playerId')}"
                skaters.append(
                    SkaterLine(
                        player_id=field(p, "playerId", where),
                        team_id=team_id,
                        position=field(p, "position", where),
                        g=field(p, "goals", where),
                        assists=field(p, "assists", where),
                        sog=field(p, "sog", where),
                        hits=field(p, "hits", where),
                        blocks=field(p, "blockedShots", where),
                        pim=field(p, "pim", where),
                        plus_minus=field(p, "plusMinus", where),
                        giveaways=field(p, "giveaways", where),
                        takeaways=field(p, "takeaways", where),
                        shifts=p.get("shifts"),
                        toi_sec=toi_seconds(field(p, "toi", where)),
                    )
                )
        for p in field(team, "goalies", f"boxscore {side}"):
            where = f"boxscore goalie {p.get('playerId')}"
            toi = toi_seconds(field(p, "toi", where))
            if toi == 0:
                continue  # dressed as the backup but did not play
            ev_sa, ev_ga = _split(p.get("evenStrengthShotsAgainst"))
            pp_sa, pp_ga = _split(p.get("powerPlayShotsAgainst"))
            sh_sa, sh_ga = _split(p.get("shorthandedShotsAgainst"))
            goalies.append(
                GoalieLine(
                    player_id=field(p, "playerId", where),
                    team_id=team_id,
                    started=bool(p.get("starter")),
                    decision=p.get("decision"),
                    shots_against=p.get("shotsAgainst", 0),
                    saves=p.get("saves", 0),
                    ga=field(p, "goalsAgainst", where),
                    ev_shots_against=ev_sa,
                    ev_ga=ev_ga,
                    pp_shots_against=pp_sa,
                    pp_ga=pp_ga,
                    sh_shots_against=sh_sa,
                    sh_ga=sh_ga,
                    toi_sec=toi,
                )
            )
    return skaters, goalies


def pbp_credits(pbp: dict) -> dict[int, dict[str, int]]:
    """Primary and secondary assists and faceoff wins and losses per player, from play-by-play.

    Shootout goals are skipped: they have no assists and do not count as goals.
    """
    credits: dict[int, dict[str, int]] = {}

    def add(player_id, key):
        if player_id:
            credits.setdefault(player_id, {"a1": 0, "a2": 0, "fow": 0, "fol": 0})[key] += 1

    for play in field(pbp, "plays", "play-by-play"):
        kind = play.get("typeDescKey")
        details = play.get("details") or {}
        if kind == "goal" and (play.get("periodDescriptor") or {}).get("periodType") != "SO":
            add(details.get("assist1PlayerId"), "a1")
            add(details.get("assist2PlayerId"), "a2")
        elif kind == "faceoff":
            add(details.get("winningPlayerId"), "fow")
            add(details.get("losingPlayerId"), "fol")
    return credits


@dataclass(frozen=True)
class PlayerInfo:
    id: int
    first_name: str
    last_name: str
    position: str | None
    team_id: int | None = None
    sweater_number: int | None = None
    headshot_url: str | None = None
    birth_date: str | None = None
    shoots: str | None = None
    height_in: int | None = None
    weight_lb: int | None = None
    birth_city: str | None = None
    birth_country: str | None = None


def pbp_players(pbp: dict) -> list[PlayerInfo]:
    """Everyone who dressed for the game, with full names (boxscores only have "F. Last")."""
    return [
        PlayerInfo(
            id=field(p, "playerId", "roster spot"),
            first_name=field(p, "firstName.default", "roster spot"),
            last_name=field(p, "lastName.default", "roster spot"),
            position=p.get("positionCode"),
            team_id=p.get("teamId"),
            sweater_number=p.get("sweaterNumber"),
            headshot_url=p.get("headshot"),
        )
        for p in field(pbp, "rosterSpots", "play-by-play")
    ]


def parse_roster(body: dict, team_id: int) -> list[PlayerInfo]:
    players = []
    for group in ("forwards", "defensemen", "goalies"):
        for p in field(body, group, "roster"):
            where = f"roster player {p.get('id')}"
            players.append(
                PlayerInfo(
                    id=field(p, "id", where),
                    first_name=field(p, "firstName.default", where),
                    last_name=field(p, "lastName.default", where),
                    position=field(p, "positionCode", where),
                    team_id=team_id,
                    sweater_number=p.get("sweaterNumber"),
                    headshot_url=p.get("headshot"),
                    birth_date=p.get("birthDate"),
                    shoots=p.get("shootsCatches"),
                    height_in=p.get("heightInInches"),
                    weight_lb=p.get("weightInPounds"),
                    birth_city=(p.get("birthCity") or {}).get("default"),
                    birth_country=p.get("birthCountry"),
                )
            )
    return players


def parse_landing(body: dict) -> PlayerInfo:
    where = f"player landing {body.get('playerId')}"
    return PlayerInfo(
        id=field(body, "playerId", where),
        first_name=field(body, "firstName.default", where),
        last_name=field(body, "lastName.default", where),
        position=body.get("position"),
        team_id=body.get("currentTeamId"),
        sweater_number=body.get("sweaterNumber"),
        headshot_url=body.get("headshot"),
        birth_date=body.get("birthDate"),
        shoots=body.get("shootsCatches"),
        height_in=body.get("heightInInches"),
        weight_lb=body.get("weightInPounds"),
        birth_city=(body.get("birthCity") or {}).get("default"),
        birth_country=body.get("birthCountry"),
    )


@dataclass(frozen=True)
class EdgeLine:
    player_id: int
    games_played: int | None
    top_speed_mph: float | None
    top_speed_pctile: float | None
    bursts_20plus: int | None
    bursts_22plus: int | None
    max_shot_speed_mph: float | None
    max_shot_speed_pctile: float | None
    distance_skated_mi: float | None
    oz_time_pct: float | None
    nz_time_pct: float | None
    dz_time_pct: float | None
    oz_time_pctile: float | None


def parse_edge(body: dict, player_id: int) -> EdgeLine:
    speed = body.get("skatingSpeed") or {}
    top_speed = speed.get("speedMax") or {}
    shot = body.get("topShotSpeed") or {}
    zones = body.get("zoneTimeDetails") or {}
    distance = body.get("totalDistanceSkated") or {}
    return EdgeLine(
        player_id=player_id,
        games_played=(body.get("player") or {}).get("gamesPlayed"),
        top_speed_mph=top_speed.get("imperial"),
        top_speed_pctile=top_speed.get("percentile"),
        bursts_20plus=(speed.get("burstsOver20") or {}).get("value"),
        bursts_22plus=(speed.get("burstsOver22") or {}).get("value"),
        max_shot_speed_mph=shot.get("imperial"),
        max_shot_speed_pctile=shot.get("percentile"),
        distance_skated_mi=distance.get("imperial"),
        oz_time_pct=zones.get("offensiveZonePctg"),
        nz_time_pct=zones.get("neutralZonePctg"),
        dz_time_pct=zones.get("defensiveZonePctg"),
        oz_time_pctile=zones.get("offensiveZonePercentile"),
    )
