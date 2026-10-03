-- 0032: PuckSleuth WAR (estimate), per player and season, from our Game Score (pipeline/models/war.py).

create table player_war (
  player_id integer not null references players (id),
  season_id integer not null,
  grp text not null check (grp in ('F', 'D', 'G')),
  gp smallint not null,
  toi_sec integer not null,
  gaa numeric(8, 3) not null,     -- Game Score total: goals above average
  gar numeric(8, 3) not null,     -- goals above replacement
  war numeric(7, 3) not null,     -- wins above replacement
  primary key (player_id, season_id)
);

create table war_constants (
  season_id integer primary key,
  goals_per_win numeric(6, 3) not null,
  replacement_f numeric(8, 4) not null,   -- Game Score per 60 of replacement-level forwards
  replacement_d numeric(8, 4) not null,   -- same for defensemen
  replacement_g numeric(8, 4) not null,   -- per game for goalies
  computed_at timestamptz not null default now()
);
