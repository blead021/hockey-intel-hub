"""Turns play-by-play into one row of features per unblocked shot, for the expected goals model.

Features (CLAUDE.md section 6): distance and angle to the net, shot type, rebound (within 3 seconds
of the same team's previous shot attempt), rush (within 4 seconds of an event outside the attacking
zone), skaters on each side, empty net, score state, and the previous event's type, time, and
distance. Blocked shots are left out: their coordinates mark the block, not the shot.

Rink coordinates: x runs -100 to 100 feet, the nets are at x = -89 and x = 89. Which net a team
attacks comes from each event's homeTeamDefendingSide.
"""

import math
from dataclasses import dataclass

from pipeline.ingest.nhl import toi_seconds

UNBLOCKED = ("shot-on-goal", "missed-shot", "goal")
SHOT_ATTEMPTS = UNBLOCKED + ("blocked-shot",)
GOAL_X = 89
BLUE_LINE_X = 25
REBOUND_SECONDS = 3
RUSH_SECONDS = 4

SHOT_TYPES = ["wrist", "snap", "slap", "backhand", "tip-in", "deflected", "wrap-around", "poke", "bat",
              "between-legs", "cradle", "other"]
PRIOR_EVENTS = ["faceoff", "hit", "giveaway", "takeaway", "shot-on-goal", "missed-shot", "blocked-shot",
                "goal", "stoppage", "penalty", "delayed-penalty", "period-start", "other"]

# Order matters: the model is trained on columns in this order.
NUMERIC = ["distance", "angle", "x_from_goal", "y_abs", "rebound", "rush", "seconds_since_prior",
           "prior_distance", "prior_same_team", "shooter_skaters", "defending_skaters", "empty_net",
           "score_diff", "period", "game_seconds"]
CATEGORICAL = ["shot_type", "prior_event"]
COLUMNS = NUMERIC + CATEGORICAL


@dataclass
class ShotRow:
    game_id: int
    event_id: int
    shooter_id: int | None
    goalie_id: int | None
    shooting_team: int
    defending_team: int
    is_goal: int
    situation: str
    features: dict
    on_goal: int = 1  # 0 for a missed shot (goals and saves are on goal)


def attacking_goal_x(shooting_is_home: bool, home_defends: str | None) -> int | None:
    """x of the net a team shoots at. Home defends one side, so it attacks the other."""
    if home_defends not in ("left", "right"):
        return None
    home_attacks = GOAL_X if home_defends == "left" else -GOAL_X
    return home_attacks if shooting_is_home else -home_attacks


def distance_angle(x: float, y: float, goal_x: int) -> tuple[float, float]:
    """Feet to the centre of the net, and degrees off the line through the net (0 = straight on)."""
    dx = abs(goal_x - x)
    distance = math.hypot(dx, y)
    angle = math.degrees(math.atan2(abs(y), dx)) if dx else 90.0
    # Shots from behind the goal line are sharper than 90 degrees.
    if (goal_x > 0 and x > goal_x) or (goal_x < 0 and x < goal_x):
        angle = 180 - angle
    return distance, angle


def zone_from(x: float | None, goal_x: int) -> str | None:
    """O, N, or D from the point of view of the team attacking goal_x."""
    if x is None:
        return None
    if abs(x) <= BLUE_LINE_X:
        return "N"
    return "O" if (x > 0) == (goal_x > 0) else "D"


def skaters(situation: str, shooting_is_home: bool) -> tuple[int, int, int]:
    """(shooter's skaters, defending skaters, defending goalie in net) from a situation code like 1551."""
    away_goalie, away_sk, home_sk, home_goalie = (int(c) for c in situation)
    if shooting_is_home:
        return home_sk, away_sk, away_goalie
    return away_sk, home_sk, home_goalie


def shot_rows(pbp: dict) -> list[ShotRow]:
    home, away = pbp["homeTeam"]["id"], pbp["awayTeam"]["id"]
    team_of = {p["playerId"]: p["teamId"] for p in pbp.get("rosterSpots", [])}
    rows: list[ShotRow] = []
    score = {home: 0, away: 0}
    prior: dict | None = None

    for play in sorted(pbp.get("plays", []), key=lambda p: p.get("sortOrder", 0)):
        period_info = play.get("periodDescriptor") or {}
        if period_info.get("periodType") == "SO":
            break
        kind = play.get("typeDescKey")
        details = play.get("details") or {}
        period = period_info.get("number") or 0
        t = toi_seconds(play.get("timeInPeriod"))
        x, y = details.get("xCoord"), details.get("yCoord")

        if kind == "period-start":
            prior = None  # nothing carries over between periods

        if kind in UNBLOCKED and x is not None and y is not None and play.get("situationCode"):
            shooter = details.get("shootingPlayerId") or details.get("scoringPlayerId")
            shooting = team_of.get(shooter) or details.get("eventOwnerTeamId")
            if shooting in (home, away):
                is_home = shooting == home
                goal_x = attacking_goal_x(is_home, play.get("homeTeamDefendingSide"))
                own, opp, opp_goalie = skaters(play["situationCode"], is_home)
                if goal_x is not None and own >= 3 and opp >= 3:  # leaves out penalty shots
                    distance, angle = distance_angle(x, y, goal_x)
                    since = (t - prior["t"]) if prior and prior["period"] == period else None
                    prior_same = bool(prior and prior["team"] == shooting)
                    prior_zone = zone_from(prior["x"], goal_x) if prior else None
                    features = {
                        "distance": distance,
                        "angle": angle,
                        "x_from_goal": abs(goal_x - x),
                        "y_abs": abs(y),
                        "rebound": int(bool(since is not None and since <= REBOUND_SECONDS and prior_same
                                            and prior["kind"] in SHOT_ATTEMPTS)),
                        "rush": int(bool(since is not None and since <= RUSH_SECONDS and prior_zone in ("N", "D"))),
                        "seconds_since_prior": since if since is not None else -1,
                        "prior_distance": (math.hypot(x - prior["x"], y - prior["y"])
                                           if prior and prior["x"] is not None and prior["y"] is not None else -1),
                        "prior_same_team": int(prior_same),
                        "shooter_skaters": own,
                        "defending_skaters": opp,
                        "empty_net": int(opp_goalie == 0),
                        "score_diff": max(-3, min(3, score[shooting] - score[away if is_home else home])),
                        "period": min(period, 4),
                        "game_seconds": (period - 1) * 1200 + t,
                        "shot_type": details.get("shotType") if details.get("shotType") in SHOT_TYPES else "other",
                        "prior_event": (prior["kind"] if prior and prior["kind"] in PRIOR_EVENTS else "other") if prior else "other",
                    }
                    rows.append(ShotRow(
                        game_id=pbp["id"], event_id=play.get("eventId"), shooter_id=shooter,
                        goalie_id=details.get("goalieInNetId"), shooting_team=shooting,
                        defending_team=away if is_home else home, is_goal=int(kind == "goal"),
                        situation=play["situationCode"], features=features, on_goal=int(kind != "missed-shot"),
                    ))

        if kind == "goal":
            scorer_team = team_of.get(details.get("scoringPlayerId")) or details.get("eventOwnerTeamId")
            if scorer_team in score:
                score[scorer_team] += 1

        owner = details.get("eventOwnerTeamId")
        if kind in SHOT_ATTEMPTS:
            owner = team_of.get(details.get("shootingPlayerId") or details.get("scoringPlayerId")) or owner
        prior = {"kind": kind, "t": t, "period": period, "x": x, "y": y, "team": owner}
    return rows
