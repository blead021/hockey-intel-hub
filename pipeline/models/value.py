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
   Age curves come from 25 seasons of NHL totals (player_season_history): points per 60 for skaters, save
   percentage for goalies.
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
GOALIE_SHRINK_SHOTS = 2000        # shots of league-average goaltending added to each goalie season


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


def history_rates(conn) -> dict[str, dict[int, dict[int, tuple[float, float, int]]]]:
    """grp -> player -> season -> (rate, weight, age) from 25 seasons of NHL totals, relative to that season's
    league level so changes in scoring and save percentage across eras do not look like aging.
    Skaters: points per 60 divided by the league's (weight: hours). Goalies: save percentage minus the
    league's, plus 0.900 to keep it on a familiar scale (weight: shots faced)."""
    league = {
        season: (pts / toi * 3600 if toi else None, sv / sa if sa else None)
        for season, pts, toi, sv, sa in conn.execute(
            """select season_id, sum(points) filter (where grp <> 'G'), sum(toi_sec) filter (where grp <> 'G'),
                      sum(saves) filter (where grp = 'G'), sum(shots_against) filter (where grp = 'G')
               from player_season_history group by season_id"""
        ).fetchall()
    }
    out: dict[str, dict[int, dict[int, tuple[float, float, int]]]] = {"F": defaultdict(dict), "D": defaultdict(dict), "G": defaultdict(dict)}
    for pid, season, grp, gp, toi, pts, sa, sv, born in conn.execute(
        """select player_id, season_id, grp, gp, toi_sec, points, shots_against, saves, birth_date
           from player_season_history where birth_date is not null"""
    ).fetchall():
        age = (date(season // 10000, 10, 1) - born).days // 365
        lg_pts, lg_sv = league.get(season, (None, None))
        if grp == "G":
            if gp >= MIN_GP["G"] and sa and lg_sv:
                # Pulled toward league average by 2,000 shots, so one lucky or unlucky season (which then
                # "declines" back to normal, or costs the job) does not read as aging.
                shrunk = (sv + GOALIE_SHRINK_SHOTS * lg_sv) / (sa + GOALIE_SHRINK_SHOTS)
                out["G"][pid][season] = (shrunk - lg_sv + 0.900, float(sa), age)
        elif gp >= MIN_GP[grp] and toi and lg_pts:
            out[grp][pid][season] = ((pts or 0) / toi * 3600 / lg_pts, toi / 3600, age)
    return out


def aging_curves(history, war_seasons) -> dict[str, dict[int, tuple[float, float, int]]]:
    """grp -> age -> (change in WAR per 82 from this age to the next, production index, pairs).

    The shape comes from 25 seasons of history (delta method: each player's change from one season to the
    next, averaged by age, weighted by the smaller season's ice time or shots, shrunk toward no change where
    pairs are few, smoothed over neighbouring ages). Index: 100 at the peak; skaters as a share of peak
    scoring rate, goalies as peak goals allowed per shot over goals allowed per shot at that age. The WAR
    change is the index change times a typical regular's WAR per 82 near the peak (our WAR seasons)."""
    out = {}
    for grp in ("F", "D", "G"):
        sums: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0, 0])
        for by_season in history[grp].values():
            for season, (rate, weight, age) in by_season.items():
                nxt = by_season.get(season + 10001) or (by_season.get(season + 20002) if season == 20032004 else None)
                if not nxt:
                    continue
                w = min(weight, nxt[1])
                acc = sums[age]
                acc[0] += (nxt[0] - rate) * w
                acc[1] += w
                acc[2] += 1
        raw = {age: (sm[0] / sm[1] * sm[2] / (sm[2] + SHRINK_PAIRS), sm[2]) for age, sm in sums.items() if sm[1] > 0}
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
        near_peak = [r for by in history[grp].values() for (r, _, a) in by.values() if abs(a - peak_age) <= 2]
        peak_rate = mean(near_peak) if near_peak else 1.0
        if grp == "G":
            index = {a: 100 * (1 - peak_rate) / max(1 - (peak_rate + levels[a] - levels[peak_age]), 1e-6) for a in ages}
        else:
            index = {a: max(0.0, 100 * (peak_rate + levels[a] - levels[peak_age]) / peak_rate) for a in ages}
        war_peak = [per82(sea) for by in war_seasons.values() for sea in by.values()
                    if sea["grp"] == grp and abs(sea["age"] - peak_age) <= 2 and sea["gp"] >= MIN_GP[grp]]
        war_scale = mean(war_peak) if war_peak else 0.0
        out[grp] = {
            a: (war_scale * (index.get(a + 1, index[a]) - index[a]) / 100, index[a], raw.get(a, (0, 0))[1]) for a in ages
        }
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
    delta = curves[last["grp"]].get(age, (0.0, 0, 0))[0]
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
    curves = aging_curves(history_rates(conn), seasons)
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
