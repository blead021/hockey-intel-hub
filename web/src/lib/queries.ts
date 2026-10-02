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
    members as (
      select id as player_id from players where ${isCurrent} and current_team_id = ${teamId} and position <> 'G'
      union
      select player_id from stats)
    select p.id, p.first_name || ' ' || p.last_name as name, p.sweater_number as number, p.position,
           date_part('year', age(p.birth_date))::int as age,
           coalesce(s.gp, 0) as gp, coalesce(s.g, 0) as g, coalesce(s.a, 0) as a, coalesce(s.pts, 0) as pts,
           coalesce(s.plus_minus, 0) as plus_minus, coalesce(s.pim, 0) as pim, coalesce(s.sog, 0) as sog,
           coalesce(s.toi_sec, 0) as toi_sec, s.pp_toi_sec, coalesce(s.fow, 0) as fow, coalesce(s.fol, 0) as fol,
           c.cap_hit, c.end_season, c.expiry_status, c.clause
    from members m
    join players p on p.id = m.player_id
    left join stats s on s.player_id = p.id
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
    members as (
      select id as player_id from players where ${isCurrent} and current_team_id = ${teamId} and position = 'G'
      union
      select player_id from stats)
    select p.id, p.first_name || ' ' || p.last_name as name, p.sweater_number as number,
           date_part('year', age(p.birth_date))::int as age,
           coalesce(s.gp, 0) as gp, coalesce(s.gs, 0) as gs, coalesce(s.w, 0) as w, coalesce(s.l, 0) as l,
           coalesce(s.otl, 0) as otl, coalesce(s.shots_against, 0) as shots_against,
           coalesce(s.saves, 0) as saves, coalesce(s.ga, 0) as ga, coalesce(s.toi_sec, 0) as toi_sec,
           c.cap_hit, c.end_season, c.expiry_status, c.clause
    from members m
    join players p on p.id = m.player_id
    left join stats s on s.player_id = p.id
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
};

export async function getSkaterSeasons(sql: Sql, playerId: number) {
  return sql<SkaterSeason[]>`
    select s.season_id, string_agg(distinct t.abbrev, ', ') as teams,
           sum(gp)::int as gp, sum(g)::int as g, sum(a)::int as a, sum(a1)::int as a1, sum(pts)::int as pts,
           sum(plus_minus)::int as plus_minus, sum(sog)::int as sog, sum(hits)::int as hits,
           sum(blocks)::int as blocks, sum(toi_sec)::int as toi_sec, sum(pp_toi_sec)::int as pp_toi_sec,
           sum(pk_toi_sec)::int as pk_toi_sec, sum(fow)::int as fow, sum(fol)::int as fol
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
};

export async function getGoalieSeasons(sql: Sql, playerId: number) {
  return sql<GoalieSeason[]>`
    select s.season_id, string_agg(distinct t.abbrev, ', ') as teams, sum(gp)::int as gp, sum(gs)::int as gs,
           sum(w)::int as w, sum(l)::int as l, sum(otl)::int as otl, sum(shots_against)::int as shots_against,
           sum(saves)::int as saves, sum(ga)::int as ga, sum(toi_sec)::int as toi_sec
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
           s.g, (s.a1 + s.a2) as a, (s.g + s.a1 + s.a2) as pts, s.plus_minus, s.sog, s.toi_sec, s.fow, s.fol
    from game_skater_stats s
    join games g on g.id = s.game_id
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
