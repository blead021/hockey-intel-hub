-- 0010: expected goals (xG) model registry, individual shooting, and goalie results.

create table xg_models (
  version text primary key,                 -- e.g. xg-2026-10-02
  trained_at timestamptz not null default now(),
  train_seasons integer[] not null,
  test_season integer not null,
  train_shots integer not null,
  test_shots integer not null,
  log_loss numeric(8, 5) not null,
  baseline_log_loss numeric(8, 5) not null,  -- distance and angle only, for comparison
  auc numeric(6, 4) not null,
  brier numeric(8, 5) not null,
  goals integer not null,                    -- in the test season
  expected_goals numeric(9, 2) not null,
  calibration jsonb not null,                -- predicted vs actual goal rate by bin
  r2_key text not null,                      -- where the model file is stored
  active boolean not null default false
);

create unique index xg_models_one_active on xg_models (active) where active;

-- Individual shooting per game, all strengths: unblocked shots, goals, and individual xG (ixG).
create table player_game_shooting (
  player_id integer not null references players (id),
  game_id integer not null references games (id) on delete cascade,
  team_id smallint not null references teams (id),
  shots integer not null,
  goals integer not null,
  ixg numeric(7, 3) not null,
  shots_5v5 integer not null,
  goals_5v5 integer not null,
  ixg_5v5 numeric(7, 3) not null,
  primary key (player_id, game_id)
);

-- Goalies per game, all strengths: unblocked shots faced, goals against, and xG against.
-- Goals saved above expected (GSAx) = xga - goals_against.
create table goalie_game_xg (
  player_id integer not null references players (id),
  game_id integer not null references games (id) on delete cascade,
  team_id smallint not null references teams (id),
  shots_faced integer not null,
  goals_against integer not null,
  xga numeric(7, 3) not null,
  primary key (player_id, game_id)
);

alter table games add column xg_version text;
