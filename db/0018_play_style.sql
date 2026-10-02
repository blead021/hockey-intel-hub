-- 0018: per-game counts behind the Play style traits (CLAUDE.md section 6), from play-by-play and shifts.

create table player_game_style (
  player_id integer not null references players (id),
  game_id integer not null references games (id) on delete cascade,
  team_id smallint not null references teams (id),
  oz_hits smallint not null,            -- his hits in the offensive zone
  oz_takeaways smallint not null,       -- his takeaways in the offensive zone
  rush_onice_5v5 smallint not null,     -- 5v5 rush attempts by his team while he was on (zone-entry ESTIMATE)
  shots_slot smallint not null,         -- his unblocked shots by location, all strengths
  shots_mid smallint not null,
  shots_perimeter smallint not null,
  primary key (player_id, game_id)
);

create index player_game_style_game_idx on player_game_style (game_id);

-- Claude-written play style text, refreshed weekly (filled once the Claude API key is set).
create table player_play_style (
  player_id integer primary key references players (id),
  season_id integer not null,
  archetype text,
  summary text,
  tags text[],
  strengths text[],
  watch_outs text[],
  model text,
  generated_at timestamptz not null default now()
);
