-- 0043: Claude's one-line reasons for undervalued players (pipeline/models/undervalued.py), refreshed nightly.
create table player_value_reasons (
  player_id integer primary key references players (id),
  reason text not null,
  model text not null,
  generated_at timestamptz not null default now()
);
