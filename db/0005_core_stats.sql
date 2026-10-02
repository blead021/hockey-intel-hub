-- 0005: game stats, EDGE skating data, and contracts (Phase 2).
-- Play-by-play and shifts live in R2, not here (see CLAUDE.md section 5).

alter table players add column sweater_number smallint;
alter table players add column headshot_url text;
alter table players add column birth_city text;
alter table players add column birth_country text;

alter table games add column venue text;
alter table games add column last_period_type text;          -- REG, OT, or SO
alter table games add column stats_loaded_at timestamptz;     -- set when boxscore, pbp, and shifts are stored

create index games_unloaded_idx on games (game_date) where stats_loaded_at is null;

create table game_skater_stats (
  player_id integer not null references players (id),
  game_id integer not null references games (id) on delete cascade,
  team_id smallint not null references teams (id),
  position text not null check (position in ('C', 'L', 'R', 'D')),
  g smallint not null default 0,
  a1 smallint not null default 0,        -- primary assists, from play-by-play
  a2 smallint not null default 0,        -- secondary assists, from play-by-play
  sog smallint not null default 0,
  hits smallint not null default 0,
  blocks smallint not null default 0,
  pim smallint not null default 0,
  plus_minus smallint not null default 0,
  giveaways smallint not null default 0,
  takeaways smallint not null default 0,
  shifts smallint,
  toi_sec integer not null default 0,
  ev_toi_sec integer,                     -- from the NHL stats API time-on-ice report
  pp_toi_sec integer,
  pk_toi_sec integer,
  fow smallint not null default 0,        -- faceoffs won and lost, from play-by-play
  fol smallint not null default 0,
  primary key (player_id, game_id)
);

create index game_skater_stats_game_idx on game_skater_stats (game_id);

create table game_goalie_stats (
  player_id integer not null references players (id),
  game_id integer not null references games (id) on delete cascade,
  team_id smallint not null references teams (id),
  started boolean not null default false,
  decision text check (decision in ('W', 'L', 'O')),
  shots_against smallint not null default 0,
  saves smallint not null default 0,
  ga smallint not null default 0,
  ev_shots_against smallint,
  ev_ga smallint,
  pp_shots_against smallint,              -- the NHL boxscore's powerPlay and shorthanded splits, as labeled
  pp_ga smallint,
  sh_shots_against smallint,
  sh_ga smallint,
  toi_sec integer not null default 0,
  primary key (player_id, game_id)
);

create index game_goalie_stats_game_idx on game_goalie_stats (game_id);

-- Season-level NHL EDGE tracking data, refreshed weekly. Percentiles are versus the league.
create table edge_player_stats (
  player_id integer not null references players (id),
  season_id integer not null references seasons (id),
  as_of date not null,
  games_played smallint,
  top_speed_mph numeric(5, 2),
  top_speed_pctile numeric(5, 4),
  bursts_20plus integer,
  bursts_22plus integer,
  max_shot_speed_mph numeric(5, 2),
  max_shot_speed_pctile numeric(5, 4),
  distance_skated_mi numeric(7, 2),
  oz_time_pct numeric(5, 4),
  nz_time_pct numeric(5, 4),
  dz_time_pct numeric(5, 4),
  oz_time_pctile numeric(5, 4),
  primary key (player_id, season_id)
);

-- Loaded from a manually maintained CSV (pipeline/ingest/contracts.py).
create table contracts (
  id serial primary key,
  player_id integer references players (id),   -- null until the name is matched
  player_name text not null,                     -- as written in the CSV
  team_id smallint references teams (id),
  cap_hit bigint not null,
  aav bigint,
  start_season integer not null,                 -- e.g. 20252026
  end_season integer not null,
  expiry_status text check (expiry_status in ('UFA', 'RFA')),
  clause text check (clause in ('NMC', 'NTC', 'M-NTC', 'none')),
  no_trade_list_size smallint,
  retained_pct numeric(5, 2) not null default 0,
  retained_by smallint references teams (id),
  loaded_at timestamptz not null default now(),
  unique (player_name, start_season)
);

create index contracts_player_idx on contracts (player_id);

-- Season totals per player and team. Points = G + A1 + A2.
create view skater_season_stats as
select
  s.player_id,
  g.season_id,
  g.game_type,
  s.team_id,
  count(*) as gp,
  sum(s.g) as g,
  sum(s.a1 + s.a2) as a,
  sum(s.a1) as a1,
  sum(s.a2) as a2,
  sum(s.g + s.a1 + s.a2) as pts,
  sum(s.sog) as sog,
  sum(s.hits) as hits,
  sum(s.blocks) as blocks,
  sum(s.pim) as pim,
  sum(s.plus_minus) as plus_minus,
  sum(s.giveaways) as giveaways,
  sum(s.takeaways) as takeaways,
  sum(s.toi_sec) as toi_sec,
  sum(s.pp_toi_sec) as pp_toi_sec,
  sum(s.pk_toi_sec) as pk_toi_sec,
  sum(s.fow) as fow,
  sum(s.fol) as fol
from game_skater_stats s
join games g on g.id = s.game_id
group by s.player_id, g.season_id, g.game_type, s.team_id;

create view goalie_season_stats as
select
  s.player_id,
  g.season_id,
  g.game_type,
  s.team_id,
  count(*) as gp,
  count(*) filter (where s.started) as gs,
  count(*) filter (where s.decision = 'W') as w,
  count(*) filter (where s.decision = 'L') as l,
  count(*) filter (where s.decision = 'O') as otl,
  sum(s.shots_against) as shots_against,
  sum(s.saves) as saves,
  sum(s.ga) as ga,
  sum(s.toi_sec) as toi_sec
from game_goalie_stats s
join games g on g.id = s.game_id
group by s.player_id, g.season_id, g.game_type, s.team_id;
