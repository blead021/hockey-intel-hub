"""Age curves, WAR projections, market value, and surplus value (CLAUDE.md section 6).

Usage:
    python -m pipeline.models.value

1. Age curves (delta method): for every player with two straight seasons of real playing time, the change
   in WAR per 82 games from one age to the next, averaged by position group and age (weighted by the
   smaller of the two seasons' games), smoothed over neighbouring ages, and summed into an index that is
   100 at the peak.
2. WAR projection, per 82 games next: the last three seasons weighted 5/4/3 by games played, with 20 games
   of replacement level (0 WAR) added so short samples are pulled toward it, plus the age curve's change.
3. Market value: among veterans (age 27+, not on entry-level deals), the straight-line relationship between
   cap share and projected WAR plus points per 82 (skaters), fitted per position group, applied to this
   player, times this season's ceiling (between the league minimum and the 20% maximum). A trend line, not an
   average of neighbours, so the very best players are not pulled down toward the players just below them.
   The 10 most similar veterans are kept as his comparables. Needs 40 weighted games over three seasons.
   Goalies get no age adjustment: four seasons of goalie data is not enough to measure an age curve.
4. Surplus = market value minus cap hit (the full cap hit, before any retention).
"""

from collections import defaultdict
from datetime import date
from math import sqrt
from statistics import mean, pstdev

from pipeline.db import connect
from pipeline.jobs import job_run

MIN_GP = {"F": 20, "D": 20, "G": 10}
WEIGHTS = (5, 4, 3)               # most recent season first
REGRESSION_GAMES = 20             # games of replacement level added to every projection
MIN_WEIGHTED_GAMES = 40           # games across three seasons before a market value is estimated
MAX_SHARE = 0.20                  # the CBA maximum contract is 20% of the ceiling
NEIGHBOURS = 10
VETERAN_AGE = 27
MIN_AGE, MAX_AGE = 19, 38
DEPTH_PTS_PER_GAME = 0.25         # a depth skater's scoring pace, for pulling short samples toward
SHRINK_PAIRS = 30                 # ages with few player-season pairs are pulled toward no change
SMOOTH = 2                        # ages either side averaged in


def season_war(conn) -> dict[int, dict[int, dict]]:
    """player -> season -> {grp, gp, war, pts, age}."""
    rows = conn.execute(
        """select w.player_id, w.season_id, w.grp, w.gp, w.war::float8,
                  coalesce((select sum(s.g + s.a1 + s.a2) from game_skater_stats s join games g on g.id = s.game_id
                            where s.player_id = w.player_id and g.season_id = w.season_id and g.game_type = 2), 0)::int,
                  date_part('year', age(make_date(w.season_id / 10000, 10, 1), p.birth_date))::int
           from player_war w join players p on p.id = w.player_id where p.birth_date is not null"""
    ).fetchall()
    out: dict[int, dict[int, dict]] = defaultdict(dict)
    for pid, season, grp, gp, war, pts, age in rows:
        out[pid][season] = {"grp": grp, "gp": gp, "war": war, "pts": pts, "age": age}
    return out


def per82(s: dict) -> float:
    return s["war"] / s["gp"] * 82


def aging_curves(seasons: dict[int, dict[int, dict]]) -> dict[str, dict[int, tuple[float, float, int]]]:
    """grp -> age -> (smoothed delta, index, pairs)."""
    sums: dict[tuple[str, int], list[float]] = defaultdict(lambda: [0.0, 0.0, 0])
    for by_season in seasons.values():
        for season, a in by_season.items():
            b = by_season.get(season + 10001)
            if not b or a["grp"] != b["grp"] or min(a["gp"], b["gp"]) < MIN_GP[a["grp"]]:
                continue
            w = min(a["gp"], b["gp"])
            acc = sums[(a["grp"], a["age"])]
            acc[0] += (per82(b) - per82(a)) * w
            acc[1] += w
            acc[2] += 1
    out = {}
    for grp in ("F", "D"):
        # Few pairs at an age: shrink toward no change, then smooth across neighbouring ages.
        raw = {age: (s[0] / s[1] * s[2] / (s[2] + SHRINK_PAIRS), s[2]) for (g, age), s in sums.items() if g == grp and s[1] > 0}
        ages = range(MIN_AGE, MAX_AGE + 1)
        smooth = {}
        for age in ages:
            near = [(raw[a][0], raw[a][1]) for a in range(age - SMOOTH, age + SMOOTH + 1) if a in raw]
            n = sum(c for _, c in near)
            smooth[age] = sum(d * c for d, c in near) / n if n else 0.0
        level, levels = 0.0, {}
        for age in ages:
            levels[age] = level
            level += smooth[age]
        peak_age = max(levels, key=levels.get)
        # Production at each age as a share of production at the peak: the typical regular's WAR per 82 at
        # the peak age, moved by the curve's change between ages.
        at_peak = [per82(s) for by in seasons.values() for s in by.values()
                   if s["grp"] == grp and abs(s["age"] - peak_age) <= 2 and s["gp"] >= MIN_GP[grp]]
        peak_rate = mean(at_peak) if at_peak else 1.0
        out[grp] = {
            age: (smooth[age], max(0.0, 100 * (peak_rate + levels[age] - levels[peak_age]) / peak_rate), raw.get(age, (0, 0))[1])
            for age in ages
        }
    # Goalies: not enough data for a curve yet; stored flat (no change, index 100) and shown as unavailable.
    out["G"] = {age: (0.0, 100.0, 0) for age in range(MIN_AGE, MAX_AGE + 1)}
    return out


def project(by_season: dict[int, dict], current: int, curves) -> tuple[float, dict] | None:
    """Projected WAR per 82 for next season, or None without recent play."""
    recent = [by_season.get(current - 10001 * i) for i in range(3)]
    if not any(recent):
        return None
    years_back, last = next((i, s) for i, s in enumerate(recent) if s)
    num = sum(w * s["war"] for w, s in zip(WEIGHTS, recent) if s)
    gp = sum(w * s["gp"] for w, s in zip(WEIGHTS, recent) if s)
    rate = num / (gp + REGRESSION_GAMES * WEIGHTS[0]) * 82
    age = last["age"] + years_back                      # his age this season
    delta = 0.0 if last["grp"] == "G" else curves[last["grp"]].get(age, (0.0, 0, 0))[0]
    # Points pulled toward a depth player's pace the same way, so a hot handful of games is not a star.
    pts = sum(w * s["pts"] for w, s in zip(WEIGHTS, recent) if s)
    pts82 = (pts + REGRESSION_GAMES * WEIGHTS[0] * DEPTH_PTS_PER_GAME) / (gp + REGRESSION_GAMES * WEIGHTS[0]) * 82
    games = sum(s["gp"] for s in recent if s)
    return rate + delta, {"grp": last["grp"], "age": age, "pts82": pts82, "games": games}


def fit_line(xs: list[list[float]], ys: list[float]) -> list[float]:
    """Least squares with an intercept (the normal equations, solved by elimination)."""
    rows = [[1.0, *x] for x in xs]
    k = len(rows[0])
    a = [[sum(r[i] * r[j] for r in rows) for j in range(k)] + [sum(r[i] * y for r, y in zip(rows, ys))] for i in range(k)]
    for i in range(k):
        pivot = max(range(i, k), key=lambda r: abs(a[r][i]))
        a[i], a[pivot] = a[pivot], a[i]
        for r in range(k):
            if r != i and a[i][i]:
                f = a[r][i] / a[i][i]
                a[r] = [x - f * y for x, y in zip(a[r], a[i])]
    return [a[i][k] / a[i][i] if a[i][i] else 0.0 for i in range(k)]


def market_values(projections: dict[int, tuple[float, dict]], contracts: dict[int, tuple[float, float]],
                  ceiling: float, min_salary: float) -> dict[int, tuple[float, list[int]]]:
    """player -> (market AAV estimate, comparable players)."""
    out = {}
    for grp in ("F", "D", "G"):
        people = {pid: p for pid, p in projections.items() if p[1]["grp"] == grp and p[1]["games"] >= MIN_WEIGHTED_GAMES}
        feats = (lambda p: [p[0]]) if grp == "G" else (lambda p: [p[0], p[1]["pts82"]])
        pool = [pid for pid, p in people.items()
                if p[1]["age"] >= VETERAN_AGE and pid in contracts and contracts[pid][1] > min_salary * 1.25]
        if len(pool) < 10:
            continue
        coef = fit_line([feats(people[q]) for q in pool], [contracts[q][0] for q in pool])
        # Comparables: nearest veterans on the same (standardized) measures plus age.
        cols = list(zip(*[feats(p) + [p[1]["age"]] for p in people.values()]))
        centre, scale = [mean(c) for c in cols], [pstdev(c) or 1.0 for c in cols]
        norm = {pid: [(v - m) / sd for v, m, sd in zip(feats(p) + [p[1]["age"]], centre, scale)] for pid, p in people.items()}
        for pid, p in people.items():
            share = coef[0] + sum(c * x for c, x in zip(coef[1:], feats(p)))
            market = min(max(share * ceiling, min_salary), MAX_SHARE * ceiling)
            near = sorted((sqrt(sum((a - b) ** 2 for a, b in zip(norm[pid], norm[q]))), q) for q in pool if q != pid)
            out[pid] = (market, [q for _, q in near[:NEIGHBOURS]])
    return out


def run(conn, counts) -> None:
    current = conn.execute("select max(season_id) from player_war").fetchone()[0]
    ceiling, min_salary = conn.execute(
        "select cap_ceiling, coalesce(min_salary, 0) from cap_limits where season_id = %s", (current,)).fetchone()
    seasons = season_war(conn)
    curves = aging_curves(seasons)
    projections = {pid: p for pid, by in seasons.items() if (p := project(by, current, curves))}
    # Cap share of each active contract, against the ceiling of the season it started (or this season).
    contracts = {
        pid: (float(share), float(hit)) for pid, share, hit in conn.execute(
            """select distinct on (c.player_id) c.player_id,
                      c.cap_hit::float8 / coalesce((select cap_ceiling from cap_limits l where l.season_id = c.start_season),
                                                   (select cap_ceiling from cap_limits l where l.season_id = %s - 10001)),
                      c.cap_hit
               from contracts c where c.status = 'active' and c.player_id is not null and c.cap_hit is not null
                 and %s between coalesce(c.start_season, 0) and c.end_season
                 and coalesce(c.contract_type, '') <> 'entry_level'
               order by c.player_id, c.end_season""",
            (current, current),
        ).fetchall()
    }
    hits = dict(conn.execute(
        """select distinct on (player_id) player_id, cap_hit::float8 from contracts
           where status = 'active' and player_id is not null and cap_hit is not null
             and %s between coalesce(start_season, 0) and end_season
           order by player_id, end_season""", (current,)).fetchall())
    markets = market_values(projections, contracts, float(ceiling), float(min_salary))
    today = date.today()
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("delete from aging_curves")
        cur.executemany(
            "insert into aging_curves (grp, age, delta, index, pairs) values (%s, %s, %s, %s, %s)",
            [(grp, age, round(d, 4), round(i, 2), n) for grp, by_age in curves.items() for age, (d, i, n) in by_age.items()],
        )
        cur.execute("delete from player_value where as_of = %s", (today,))
        cur.executemany(
            """insert into player_value (player_id, as_of, war_proj, market_aav_est, surplus, comps)
               values (%s, %s, %s, %s, %s, %s)""",
            [(pid, today, round(proj[0], 3),
              round(markets[pid][0]) if pid in markets else None,
              round(markets[pid][0] - hits[pid]) if pid in markets and pid in hits else None,
              markets[pid][1] if pid in markets else None)
             for pid, proj in projections.items()],
        )
    counts["projections"] = len(projections)
    counts["market_values"] = len(markets)


def main() -> None:
    with job_run("player_value") as counts, connect() as conn:
        run(conn, counts)
    print(f"player value ok: {dict(counts)}")


if __name__ == "__main__":
    main()
