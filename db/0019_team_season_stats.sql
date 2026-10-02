-- 0019: official team season totals from the NHL stats API (record, points, PP%, PK%), refreshed nightly.

create table team_season_stats (
  team_id smallint not null references teams (id),
  season_id integer not null references seasons (id),
  gp smallint not null,
  w smallint not null,
  l smallint not null,
  otl smallint not null,
  points smallint not null,
  goals_for smallint not null,
  goals_against smallint not null,
  pp_pct numeric(6, 4),
  pk_pct numeric(6, 4),
  updated_at timestamptz not null default now(),
  primary key (team_id, season_id)
);
