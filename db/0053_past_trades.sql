-- 0053: past trades assembled from the contracts job's confirmed trade and draft pick transactions, for the Trade
-- Builder's comparable trades. Rebuilt in full by `python -m pipeline.models.past_trades` (nightly).

create table past_trades (
  id serial primary key,
  traded_on date not null,
  team_a smallint not null references teams (id),
  team_b smallint not null references teams (id),
  source_urls text[]
);

create table past_trade_items (
  trade_id integer not null references past_trades (id) on delete cascade,
  to_team_id smallint not null references teams (id),
  kind text not null check (kind in ('player', 'pick')),
  player_id integer references players (id),
  name text,                    -- player name, or a pick label such as "2027 2nd (TOR)"
  position text,
  age integer,                  -- at the trade
  cap_hit numeric(12, 0),       -- the contract in force at the trade (before retention)
  retained_pct numeric(5, 2),
  war_rate numeric(6, 2),       -- WAR per 82 games over the season of the trade and the one before
  gp integer,                   -- games behind war_rate
  pick_year integer,
  pick_round integer
);

create index past_trade_items_player_idx on past_trade_items (player_id);
