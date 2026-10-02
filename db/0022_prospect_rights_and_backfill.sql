-- 0022: prospects and the one-time contract backfill for players on NHL contracts who are not in the starting file.

-- The team holding a player's NHL rights, from the NHL's prospect lists (players not on an NHL roster).
alter table players add column rights_team_id smallint references teams (id);

-- 'backfill' headlines wait for Brian's approval before the contracts job sends them to Claude.
alter table contract_news drop constraint contract_news_status_check;
alter table contract_news add constraint contract_news_status_check
  check (status in ('pending', 'skipped', 'extracted', 'failed', 'backfill'));

-- One news search per player, so a rerun never searches the same player twice.
create table contract_backfill_searches (
  player_id integer primary key references players (id),
  searched_at timestamptz not null default now(),
  headlines integer not null,
  kept integer not null
);
