-- 0013: drop HockeyStatCards (Brian decided 2026-10-02) and add our own Game Score in goals above average.

update data_sources
set enabled = false,
    notes = 'Dropped 2026-10-02: our own Game Score (goals above average) replaces it. '
         || 'Everything on its cards can be built from NHL play-by-play and our xG model.',
    updated_at = now()
where key = 'hockeystatcards';

-- On-ice expected goals on the power play (player's team has more skaters) and penalty kill
-- (fewer skaters), both goalies in net. Filled by pipeline/metrics/onice.py.
alter table player_game_onice add column pp_xgf numeric(6, 3);
alter table player_game_onice add column pp_xga numeric(6, 3);
alter table player_game_onice add column sh_xgf numeric(6, 3);
alter table player_game_onice add column sh_xga numeric(6, 3);

-- Our Game Score per player per game, in goals above an average player with the same ice time.
-- Components are stored so pages can show where a score came from. See pipeline/metrics/game_score.py.
create table player_game_score (
  player_id integer not null references players (id),
  game_id integer not null references games (id) on delete cascade,
  team_id smallint not null references teams (id),
  is_goalie boolean not null,
  ev_offense numeric(6, 3) not null default 0,
  ev_defense numeric(6, 3) not null default 0,
  power_play numeric(6, 3) not null default 0,
  penalty_kill numeric(6, 3) not null default 0,
  finishing numeric(6, 3) not null default 0,
  playmaking numeric(6, 3) not null default 0,
  penalties numeric(6, 3) not null default 0,
  faceoffs numeric(6, 3) not null default 0,
  goaltending numeric(6, 3) not null default 0,
  game_score numeric(6, 3) not null,
  computed_at timestamptz not null default now(),
  primary key (player_id, game_id)
);

create index player_game_score_game_idx on player_game_score (game_id);
