import type { Sql } from "./db";

// All reads for the Team Roster and Player Profile pages. Season numbers cover the regular
// season only (game_type 2); playoffs get their own tables later.

export type Team = { id: number; abbrev: string; name: string; conference: string | null; division: string | null };

export async function getTeams(sql: Sql): Promise<Team[]> {
  return sql<Team[]>`
    select id, abbrev, name, conference, division from teams where active order by name`;
}

export async function getTeam(sql: Sql, abbrev: string): Promise<Team | undefined> {
  const [team] = await sql<Team[]>`
    select id, abbrev, name, conference, division from teams where active and abbrev = ${abbrev.toUpperCase()}`;
  return team;
}

// Seasons that have at least one loaded game, newest first.
export async function getLoadedSeasons(sql: Sql): Promise<number[]> {
  const rows = await sql<{ season_id: number }[]>`
    select distinct season_id from games where stats_loaded_at is not null order by season_id desc`;
  return rows.map((r) => r.season_id);
}

export async function getEnabledSources(sql: Sql): Promise<Set<string>> {
  const rows = await sql<{ key: string }[]>`select key from data_sources where enabled`;
  return new Set(rows.map((r) => r.key));
}

export type TeamRecord = { gp: number; w: number; l: number; otl: number; gf: number; ga: number };

export async function getTeamRecord(sql: Sql, teamId: number, season: number): Promise<TeamRecord> {
  const [row] = await sql<TeamRecord[]>`
    with g as (
      select case when home_team_id = ${teamId} then home_score else away_score end as gf,
             case when home_team_id = ${teamId} then away_score else home_score end as ga,
             last_period_type
      from games
      where season_id = ${season} and game_type = 2 and stats_loaded_at is not null
        and ${teamId} in (home_team_id, away_team_id))
    select count(*)::int as gp,
           count(*) filter (where gf > ga)::int as w,
           count(*) filter (where gf < ga and last_period_type = 'REG')::int as l,
           count(*) filter (where gf < ga and last_period_type <> 'REG')::int as otl,
           coalesce(sum(gf), 0)::int as gf,
           coalesce(sum(ga), 0)::int as ga
    from g`;
  return row;
}

export async function getTeamXgfPct(sql: Sql, teamId: number, season: number): Promise<number | null> {
  const [row] = await sql<{ xgf_pct: number | null }[]>`
    select xgf::float8 / nullif(xgf + xga, 0)::float8 as xgf_pct from team_season_onice
    where team_id = ${teamId} and season_id = ${season} and game_type = 2`;
  return row?.xgf_pct ?? null;
}

export type RosterSkater = {
  id: number;
  name: string;
  number: number | null;
  position: string;
  age: number | null;
  gp: number;
  g: number;
  a: number;
  pts: number;
  plus_minus: number;
  pim: number;
  sog: number;
  toi_sec: number;
  pp_toi_sec: number | null;
  fow: number;
  fol: number;
  xgf_pct: number | null;
  cap_hit: number | null;
  end_season: number | null;
  expiry_status: string | null;
  clause: string | null;
};

// Current season: today's roster (with zero-game players). Past seasons: everyone who played for the team.
export async function getRosterSkaters(sql: Sql, teamId: number, season: number, isCurrent: boolean) {
  return sql<RosterSkater[]>`
    with stats as (
      select player_id, sum(gp)::int as gp, sum(g)::int as g, sum(a)::int as a, sum(pts)::int as pts,
             sum(plus_minus)::int as plus_minus, sum(pim)::int as pim, sum(sog)::int as sog,
             sum(toi_sec)::int as toi_sec, sum(pp_toi_sec)::int as pp_toi_sec,
             sum(fow)::int as fow, sum(fol)::int as fol
      from skater_season_stats
      where team_id = ${teamId} and season_id = ${season} and game_type = 2
      group by player_id),
    onice as (
      select player_id, sum(xgf)::float8 / nullif(sum(xgf + xga), 0)::float8 as xgf_pct
      from skater_season_onice where team_id = ${teamId} and season_id = ${season} and game_type = 2
      group by player_id),
    members as (
      select id as player_id from players where ${isCurrent} and current_team_id = ${teamId} and position <> 'G'
      union
      select player_id from stats)
    select p.id, p.first_name || ' ' || p.last_name as name, p.sweater_number as number, p.position,
           date_part('year', age(p.birth_date))::int as age,
           coalesce(s.gp, 0) as gp, coalesce(s.g, 0) as g, coalesce(s.a, 0) as a, coalesce(s.pts, 0) as pts,
           coalesce(s.plus_minus, 0) as plus_minus, coalesce(s.pim, 0) as pim, coalesce(s.sog, 0) as sog,
           coalesce(s.toi_sec, 0) as toi_sec, s.pp_toi_sec, coalesce(s.fow, 0) as fow, coalesce(s.fol, 0) as fol,
           oi.xgf_pct,
           c.cap_hit, c.end_season, c.expiry_status, c.clause
    from members m
    join players p on p.id = m.player_id
    left join stats s on s.player_id = p.id
    left join onice oi on oi.player_id = p.id
    left join lateral (
      select cap_hit, end_season, expiry_status, clause from contracts
      where player_id = p.id and status = 'active' and ${season} between start_season and end_season
      order by start_season desc limit 1) c on true
    order by pts desc, g desc, toi_sec desc, name`;
}

export type RosterGoalie = {
  id: number;
  name: string;
  number: number | null;
  age: number | null;
  gp: number;
  gs: number;
  w: number;
  l: number;
  otl: number;
  shots_against: number;
  saves: number;
  ga: number;
  toi_sec: number;
  gsax: number | null;
  cap_hit: number | null;
  end_season: number | null;
  expiry_status: string | null;
  clause: string | null;
};

export async function getRosterGoalies(sql: Sql, teamId: number, season: number, isCurrent: boolean) {
  return sql<RosterGoalie[]>`
    with stats as (
      select player_id, sum(gp)::int as gp, sum(gs)::int as gs, sum(w)::int as w, sum(l)::int as l,
             sum(otl)::int as otl, sum(shots_against)::int as shots_against, sum(saves)::int as saves,
             sum(ga)::int as ga, sum(toi_sec)::int as toi_sec
      from goalie_season_stats
      where team_id = ${teamId} and season_id = ${season} and game_type = 2
      group by player_id),
    gx as (
      -- Goals saved above expected, with the season adjustment.
      select x.player_id, sum(x.xga)::float8 * coalesce(max(f.factor), 1)::float8 - sum(x.goals_against)::float8 as gsax
      from goalie_season_xg x left join xg_season_factor f on f.season_id = x.season_id
      where x.team_id = ${teamId} and x.season_id = ${season} and x.game_type = 2
      group by x.player_id),
    members as (
      select id as player_id from players where ${isCurrent} and current_team_id = ${teamId} and position = 'G'
      union
      select player_id from stats)
    select p.id, p.first_name || ' ' || p.last_name as name, p.sweater_number as number,
           date_part('year', age(p.birth_date))::int as age,
           coalesce(s.gp, 0) as gp, coalesce(s.gs, 0) as gs, coalesce(s.w, 0) as w, coalesce(s.l, 0) as l,
           coalesce(s.otl, 0) as otl, coalesce(s.shots_against, 0) as shots_against,
           coalesce(s.saves, 0) as saves, coalesce(s.ga, 0) as ga, coalesce(s.toi_sec, 0) as toi_sec,
           gx.gsax,
           c.cap_hit, c.end_season, c.expiry_status, c.clause
    from members m
    join players p on p.id = m.player_id
    left join stats s on s.player_id = p.id
    left join gx on gx.player_id = p.id
    left join lateral (
      select cap_hit, end_season, expiry_status, clause from contracts
      where player_id = p.id and status = 'active' and ${season} between start_season and end_season
      order by start_season desc limit 1) c on true
    order by gp desc, name`;
}

export async function getCapCeiling(sql: Sql, season: number): Promise<number | null> {
  const [row] = await sql<{ cap_ceiling: number }[]>`
    select cap_ceiling::float8 as cap_ceiling from cap_limits where season_id = ${season}`;
  return row?.cap_ceiling ?? null;
}

export type Player = {
  id: number;
  first_name: string;
  last_name: string;
  position: string | null;
  number: number | null;
  headshot_url: string | null;
  birth_date: string | null;
  age: number | null;
  shoots: string | null;
  height_in: number | null;
  weight_lb: number | null;
  birth_city: string | null;
  birth_country: string | null;
  team_abbrev: string | null;
  team_name: string | null;
};

export async function getPlayer(sql: Sql, id: number): Promise<Player | undefined> {
  const [row] = await sql<Player[]>`
    select p.id, p.first_name, p.last_name, p.position, p.sweater_number as number, p.headshot_url,
           to_char(p.birth_date, 'YYYY-MM-DD') as birth_date, date_part('year', age(p.birth_date))::int as age,
           p.shoots, p.height_in, p.weight_lb, p.birth_city, p.birth_country,
           t.abbrev as team_abbrev, t.name as team_name
    from players p left join teams t on t.id = p.current_team_id
    where p.id = ${id}`;
  return row;
}

export type SkaterSeason = {
  season_id: number;
  teams: string;
  gp: number;
  g: number;
  a: number;
  a1: number;
  pts: number;
  plus_minus: number;
  sog: number;
  hits: number;
  blocks: number;
  toi_sec: number;
  pp_toi_sec: number | null;
  pk_toi_sec: number | null;
  fow: number;
  fol: number;
  game_score: number | null;
};

export async function getSkaterSeasons(sql: Sql, playerId: number) {
  return sql<SkaterSeason[]>`
    select s.season_id, string_agg(distinct t.abbrev, ', ') as teams,
           sum(gp)::int as gp, sum(g)::int as g, sum(a)::int as a, sum(a1)::int as a1, sum(pts)::int as pts,
           sum(plus_minus)::int as plus_minus, sum(sog)::int as sog, sum(hits)::int as hits,
           sum(blocks)::int as blocks, sum(toi_sec)::int as toi_sec, sum(pp_toi_sec)::int as pp_toi_sec,
           sum(pk_toi_sec)::int as pk_toi_sec, sum(fow)::int as fow, sum(fol)::int as fol,
           (select avg(gs.game_score)::float8 from player_game_score gs join games g on g.id = gs.game_id
              where gs.player_id = ${playerId} and g.season_id = s.season_id and g.game_type = 2) as game_score
    from skater_season_stats s join teams t on t.id = s.team_id
    where s.player_id = ${playerId} and s.game_type = 2
    group by s.season_id order by s.season_id desc`;
}

export type GoalieSeason = {
  season_id: number;
  teams: string;
  gp: number;
  gs: number;
  w: number;
  l: number;
  otl: number;
  shots_against: number;
  saves: number;
  ga: number;
  toi_sec: number;
  gsax: number | null;
  game_score: number | null;
};

export async function getGoalieSeasons(sql: Sql, playerId: number) {
  return sql<GoalieSeason[]>`
    select s.season_id, string_agg(distinct t.abbrev, ', ') as teams, sum(gp)::int as gp, sum(gs)::int as gs,
           sum(w)::int as w, sum(l)::int as l, sum(otl)::int as otl, sum(shots_against)::int as shots_against,
           sum(saves)::int as saves, sum(ga)::int as ga, sum(toi_sec)::int as toi_sec,
           (select sum(x.xga)::float8 * coalesce(max(f.factor), 1)::float8 - sum(x.goals_against)::float8
              from goalie_season_xg x left join xg_season_factor f on f.season_id = x.season_id
              where x.player_id = ${playerId} and x.season_id = s.season_id and x.game_type = 2) as gsax,
           (select avg(gs.game_score)::float8 from player_game_score gs join games g on g.id = gs.game_id
              where gs.player_id = ${playerId} and g.season_id = s.season_id and g.game_type = 2) as game_score
    from goalie_season_stats s join teams t on t.id = s.team_id
    where s.player_id = ${playerId} and s.game_type = 2
    group by s.season_id order by s.season_id desc`;
}

export type SkaterGame = {
  game_id: number;
  game_date: string;
  opponent: string;
  home: boolean;
  result: string;
  g: number;
  a: number;
  pts: number;
  plus_minus: number;
  sog: number;
  toi_sec: number;
  fow: number;
  fol: number;
  game_score: number | null;
};

export async function getSkaterLastGames(sql: Sql, playerId: number, limit = 5) {
  return sql<SkaterGame[]>`
    select g.id as game_id, to_char(g.game_date, 'YYYY-MM-DD') as game_date,
           case when g.home_team_id = s.team_id then away.abbrev else home.abbrev end as opponent,
           g.home_team_id = s.team_id as home,
           case
             when (g.home_team_id = s.team_id) = (g.home_score > g.away_score) then 'W'
             when g.last_period_type = 'REG' then 'L' else 'OTL'
           end || ' ' || greatest(g.home_score, g.away_score) || '-' || least(g.home_score, g.away_score) as result,
           s.g, (s.a1 + s.a2) as a, (s.g + s.a1 + s.a2) as pts, s.plus_minus, s.sog, s.toi_sec, s.fow, s.fol,
           gs.game_score::float8 as game_score
    from game_skater_stats s
    join games g on g.id = s.game_id
    left join player_game_score gs on gs.player_id = s.player_id and gs.game_id = s.game_id
    join teams home on home.id = g.home_team_id
    join teams away on away.id = g.away_team_id
    where s.player_id = ${playerId}
    order by g.game_date desc, g.id desc limit ${limit}`;
}

export type Contract = {
  cap_hit: number;
  aav: number | null;
  start_season: number;
  end_season: number;
  expiry_status: string | null;
  clause: string | null;
  no_trade_list_size: number | null;
  retained_pct: number;
};

export async function getCurrentContract(sql: Sql, playerId: number, season: number): Promise<Contract | undefined> {
  const [row] = await sql<Contract[]>`
    select cap_hit::float8 as cap_hit, aav::float8 as aav, start_season, end_season, expiry_status, clause,
           no_trade_list_size, retained_pct::float8 as retained_pct
    from contracts where player_id = ${playerId} and status = 'active' and ${season} between start_season and end_season
    order by start_season desc limit 1`;
  return row;
}

export type Edge = {
  season_id: number;
  as_of: string;
  top_speed_mph: number | null;
  top_speed_pctile: number | null;
  bursts_20plus: number | null;
  max_shot_speed_mph: number | null;
  max_shot_speed_pctile: number | null;
  distance_skated_mi: number | null;
  oz_time_pct: number | null;
  dz_time_pct: number | null;
  oz_time_pctile: number | null;
};

export async function getLatestEdge(sql: Sql, playerId: number): Promise<Edge | undefined> {
  const [row] = await sql<Edge[]>`
    select season_id, to_char(as_of, 'YYYY-MM-DD') as as_of, top_speed_mph::float8 as top_speed_mph,
           top_speed_pctile::float8 as top_speed_pctile, bursts_20plus,
           max_shot_speed_mph::float8 as max_shot_speed_mph, max_shot_speed_pctile::float8 as max_shot_speed_pctile,
           distance_skated_mi::float8 as distance_skated_mi, oz_time_pct::float8 as oz_time_pct,
           dz_time_pct::float8 as dz_time_pct, oz_time_pctile::float8 as oz_time_pctile
    from edge_player_stats where player_id = ${playerId} order by season_id desc limit 1`;
  return row;
}

export type ContractChangeEvent = {
  id: number;
  created_at: string;
  player_name: string;
  player_id: number | null;
  event_type: string;
  event_status: string;
  outcome: string;
  outcome_note: string | null;
  source_urls: string[];
  changes: { field: string; old: string | null; new: string | null }[];
};

// What the daily contract news job did, newest first, with sources.
export async function getContractEvents(sql: Sql, days = 30) {
  return sql<ContractChangeEvent[]>`
    select e.id, to_char(e.created_at at time zone 'UTC', 'YYYY-MM-DD HH24:MI') as created_at, e.player_name,
           e.player_id, e.event_type, e.event_status, e.outcome, e.outcome_note, e.source_urls,
           coalesce(json_agg(json_build_object('field', c.field, 'old', c.old_value, 'new', c.new_value)
                             order by c.id) filter (where c.id is not null), '[]') as changes
    from contract_events e left join contract_changes c on c.event_id = e.id
    where e.created_at > now() - make_interval(days => ${days})
    group by e.id order by e.created_at desc, e.id desc`;
}

export type AdvancedMetric = { key: string; value: number | null; pctile: number | null };
export type SkaterAdvanced = { season_id: number; gp: number; toi_5v5_sec: number; ranked: boolean; metrics: AdvancedMetric[] };

// 5v5 on-ice results for one season, with percentiles among skaters at the same position
// (forwards or defense) who played at least 100 minutes at 5v5. Lower is better for CA/60.
export async function getSkaterAdvanced(sql: Sql, playerId: number, season: number): Promise<SkaterAdvanced | undefined> {
  const rows = await sql<
    {
      season_id: number; gp: number; toi_5v5_sec: number; ranked: boolean;
      cf_pct: number | null; rel_cf_pct: number | null; ff_pct: number | null; gf_pct: number | null;
      pdo: number | null; ozs_pct: number | null; cf60: number | null; ca60: number | null;
      xgf_pct: number | null; rel_xgf_pct: number | null; hdcf_pct: number | null;
      ixg: number | null; gax: number | null; ixg60: number | null; ipp: number | null;
      p_cf_pct: number | null; p_rel_cf_pct: number | null; p_ff_pct: number | null; p_gf_pct: number | null;
      p_pdo: number | null; p_ozs_pct: number | null; p_cf60: number | null; p_ca60: number | null;
      p_xgf_pct: number | null; p_rel_xgf_pct: number | null; p_hdcf_pct: number | null;
      p_gax: number | null; p_ixg60: number | null; p_ipp: number | null;
    }[]
  >`
    with totals as (
      select o.player_id, o.season_id,
             case when p.position = 'D' then 'D' else 'F' end as grp,
             sum(gp)::int as gp, sum(toi_5v5_sec)::int as toi, sum(cf)::float8 as cf, sum(ca)::float8 as ca,
             sum(ff)::float8 as ff, sum(fa)::float8 as fa, sum(sf)::float8 as sf, sum(sa)::float8 as sa,
             sum(gf)::float8 as gf, sum(ga)::float8 as ga, sum(oz_starts)::float8 as oz, sum(dz_starts)::float8 as dz,
             sum(off_cf)::float8 as off_cf, sum(off_ca)::float8 as off_ca,
             sum(xgf)::float8 as xgf, sum(xga)::float8 as xga, sum(hdcf)::float8 as hdcf, sum(hdca)::float8 as hdca,
             sum(off_xgf)::float8 as off_xgf, sum(off_xga)::float8 as off_xga
      from skater_season_onice o join players p on p.id = o.player_id
      where o.season_id = ${season} and o.game_type = 2
      group by o.player_id, o.season_id, grp),
    shooting as (
      -- All strengths. Expected goals use the season adjustment (league xG scaled to league goals).
      select s.player_id, sum(s.goals)::float8 as goals, sum(s.ixg)::float8 * coalesce(max(f.factor), 1)::float8 as ixg
      from skater_season_shooting s left join xg_season_factor f on f.season_id = s.season_id
      where s.season_id = ${season} and s.game_type = 2
      group by s.player_id),
    even_points as (
      select s.player_id, sum(s.points_5v5)::float8 as pts
      from game_skater_stats s join games g on g.id = s.game_id
      where g.season_id = ${season} and g.game_type = 2
        and exists (select 1 from player_game_onice o where o.player_id = s.player_id and o.game_id = s.game_id)
      group by s.player_id),
    metrics as (
      select player_id, season_id, grp, gp, toi, toi >= 6000 as ranked,
             cf / nullif(cf + ca, 0) as cf_pct,
             cf / nullif(cf + ca, 0) - off_cf / nullif(off_cf + off_ca, 0) as rel_cf_pct,
             ff / nullif(ff + fa, 0) as ff_pct,
             gf / nullif(gf + ga, 0) as gf_pct,
             (gf / nullif(sf, 0) + 1 - ga / nullif(sa, 0)) * 100 as pdo,
             oz / nullif(oz + dz, 0) as ozs_pct,
             cf * 3600 / nullif(toi, 0) as cf60,
             ca * 3600 / nullif(toi, 0) as ca60,
             xgf / nullif(xgf + xga, 0) as xgf_pct,
             xgf / nullif(xgf + xga, 0) - off_xgf / nullif(off_xgf + off_xga, 0) as rel_xgf_pct,
             hdcf / nullif(hdcf + hdca, 0) as hdcf_pct,
             sh.ixg as ixg,
             sh.goals - sh.ixg as gax,
             sh.ixg * 3600 / nullif(toi, 0) as ixg60,
             ep.pts / nullif(gf, 0) as ipp
      from totals left join shooting sh using (player_id) left join even_points ep using (player_id)),
    ranked as (
      select m.*,
        case when ranked then percent_rank() over (partition by grp, ranked order by cf_pct nulls first) end as p_cf_pct,
        case when ranked then percent_rank() over (partition by grp, ranked order by rel_cf_pct nulls first) end as p_rel_cf_pct,
        case when ranked then percent_rank() over (partition by grp, ranked order by ff_pct nulls first) end as p_ff_pct,
        case when ranked then percent_rank() over (partition by grp, ranked order by gf_pct nulls first) end as p_gf_pct,
        case when ranked then percent_rank() over (partition by grp, ranked order by pdo nulls first) end as p_pdo,
        case when ranked then percent_rank() over (partition by grp, ranked order by ozs_pct nulls first) end as p_ozs_pct,
        case when ranked then percent_rank() over (partition by grp, ranked order by cf60 nulls first) end as p_cf60,
        case when ranked then percent_rank() over (partition by grp, ranked order by ca60 desc nulls first) end as p_ca60,
        case when ranked then percent_rank() over (partition by grp, ranked order by xgf_pct nulls first) end as p_xgf_pct,
        case when ranked then percent_rank() over (partition by grp, ranked order by rel_xgf_pct nulls first) end as p_rel_xgf_pct,
        case when ranked then percent_rank() over (partition by grp, ranked order by hdcf_pct nulls first) end as p_hdcf_pct,
        case when ranked then percent_rank() over (partition by grp, ranked order by gax nulls first) end as p_gax,
        case when ranked then percent_rank() over (partition by grp, ranked order by ixg60 nulls first) end as p_ixg60,
        case when ranked then percent_rank() over (partition by grp, ranked order by ipp nulls first) end as p_ipp
      from metrics m)
    select season_id, gp, toi as toi_5v5_sec, ranked, cf_pct, rel_cf_pct, ff_pct, gf_pct, pdo, ozs_pct, cf60, ca60,
           xgf_pct, rel_xgf_pct, hdcf_pct, ixg, gax, ixg60, ipp,
           p_cf_pct, p_rel_cf_pct, p_ff_pct, p_gf_pct, p_pdo, p_ozs_pct, p_cf60, p_ca60,
           p_xgf_pct, p_rel_xgf_pct, p_hdcf_pct, p_gax, p_ixg60, p_ipp
    from ranked where player_id = ${playerId}`;
  const r = rows[0];
  if (!r) return undefined;
  const m = (key: string, value: number | null, pctile: number | null) => ({ key, value, pctile });
  return {
    season_id: r.season_id,
    gp: r.gp,
    toi_5v5_sec: r.toi_5v5_sec,
    ranked: r.ranked,
    metrics: [
      m("xGF%", r.xgf_pct, r.p_xgf_pct),
      m("Relative xGF%", r.rel_xgf_pct, r.p_rel_xgf_pct),
      m("HDCF%", r.hdcf_pct, r.p_hdcf_pct),
      m("CF%", r.cf_pct, r.p_cf_pct),
      m("Relative CF%", r.rel_cf_pct, r.p_rel_cf_pct),
      m("FF%", r.ff_pct, r.p_ff_pct),
      m("GF%", r.gf_pct, r.p_gf_pct),
      m("CF/60", r.cf60, r.p_cf60),
      m("CA/60", r.ca60, r.p_ca60),
      m("ixG/60", r.ixg60, r.p_ixg60),
      m("Goals above expected", r.gax, r.p_gax),
      m("IPP", r.ipp, r.p_ipp),
      m("PDO", r.pdo, r.p_pdo),
      m("OZS%", r.ozs_pct, r.p_ozs_pct),
    ],
  };
}

export type GameScoreBreakdown = {
  season_id: number;
  gp: number;
  total: number;
  per_game: number;
  parts: { key: string; value: number }[];
};

// Season totals of each Game Score part (goals above average), for the profile breakdown.
export async function getGameScoreBreakdown(sql: Sql, playerId: number, season: number): Promise<GameScoreBreakdown | undefined> {
  const [r] = await sql<
    { gp: number; ev_offense: number; ev_defense: number; power_play: number; penalty_kill: number; finishing: number;
      playmaking: number; penalties: number; faceoffs: number; goaltending: number; total: number }[]
  >`
    select count(*)::int as gp, sum(ev_offense)::float8 as ev_offense, sum(ev_defense)::float8 as ev_defense,
           sum(power_play)::float8 as power_play, sum(penalty_kill)::float8 as penalty_kill,
           sum(finishing)::float8 as finishing, sum(playmaking)::float8 as playmaking,
           sum(penalties)::float8 as penalties, sum(faceoffs)::float8 as faceoffs,
           sum(goaltending)::float8 as goaltending, sum(game_score)::float8 as total
    from player_game_score gs join games g on g.id = gs.game_id
    where gs.player_id = ${playerId} and g.season_id = ${season} and g.game_type = 2`;
  if (!r || !r.gp) return undefined;
  const parts = [
    { key: "Even strength offense", value: r.ev_offense },
    { key: "Even strength defense", value: r.ev_defense },
    { key: "Power play", value: r.power_play },
    { key: "Penalty kill", value: r.penalty_kill },
    { key: "Finishing", value: r.finishing },
    { key: "Playmaking", value: r.playmaking },
    { key: "Penalties", value: r.penalties },
    { key: "Faceoffs", value: r.faceoffs },
    { key: "Goaltending", value: r.goaltending },
  ].filter((p) => Math.abs(p.value) >= 0.05);
  return { season_id: season, gp: r.gp, total: r.total, per_game: r.total / r.gp, parts };
}

// The season to show advanced metrics for: the most recent one with at least 100 minutes at 5v5
// (early in a season that is usually last season), or else the most recent one with any data.
export async function getLatestOniceSeason(sql: Sql, playerId: number): Promise<number | undefined> {
  const [row] = await sql<{ season_id: number | null }[]>`
    select coalesce(max(season_id) filter (where toi >= 6000), max(season_id)) as season_id
    from (select g.season_id, sum(o.toi_5v5_sec) as toi from player_game_onice o join games g on g.id = o.game_id
          where o.player_id = ${playerId} and g.game_type = 2 group by g.season_id) s`;
  return row?.season_id ?? undefined;
}
