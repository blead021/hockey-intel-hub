-- 0008: 5v5 on-ice results per player and per team, per game (Phase 3).
-- Computed from play-by-play and shift files in R2 by pipeline/metrics/onice.py.
-- xG columns stay empty until an expected-goals source is in place.

create table player_game_onice (
  player_id integer not null references players (id),
  game_id integer not null references games (id) on delete cascade,
  team_id smallint not null references teams (id),
  toi_5v5_sec integer not null,
  cf smallint not null,   -- shot attempts for (goals, shots on goal, missed, blocked) while on ice
  ca smallint not null,
  ff smallint not null,   -- unblocked attempts (Fenwick)
  fa smallint not null,
  sf smallint not null,   -- shots on goal, including goals
  sa smallint not null,
  gf smallint not null,
  ga smallint not null,
  xgf numeric(6, 3),
  xga numeric(6, 3),
  hdcf smallint,          -- high-danger chances (needs xG)
  hdca smallint,
  oz_starts smallint not null,  -- shifts that began at a 5v5 faceoff in each zone, from the player's view
  nz_starts smallint not null,
  dz_starts smallint not null,
  primary key (player_id, game_id)
);

create index player_game_onice_game_idx on player_game_onice (game_id);

create table team_game_onice (
  team_id smallint not null references teams (id),
  game_id integer not null references games (id) on delete cascade,
  toi_5v5_sec integer not null,
  cf smallint not null,
  ca smallint not null,
  ff smallint not null,
  fa smallint not null,
  sf smallint not null,
  sa smallint not null,
  gf smallint not null,
  ga smallint not null,
  xgf numeric(6, 3),
  xga numeric(6, 3),
  hdcf smallint,
  hdca smallint,
  primary key (team_id, game_id)
);

alter table games add column onice_loaded_at timestamptz;
