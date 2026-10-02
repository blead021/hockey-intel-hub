-- 0015: which players each mention is about (Phase 4). Matching is free and runs first;
-- Claude scoring later fills sentiment, is_trade_related, and summary, and confirms the player.

create table mention_players (
  mention_id bigint not null references mentions (id) on delete cascade,
  player_id integer not null references players (id),
  confidence numeric(4, 3) not null,
  match_method text not null,           -- full_name, surname, surname_context, nickname
  status text not null check (status in ('matched', 'needs_review', 'rejected')),
  sentiment numeric(4, 3) check (sentiment between -1 and 1),
  is_trade_related boolean,
  summary text,
  scored_at timestamptz,
  scored_by text,                       -- model id
  primary key (mention_id, player_id)
);

create index mention_players_player_idx on mention_players (player_id, status);

alter table mentions add column matched_at timestamptz;
create index mentions_unmatched_idx on mentions (id) where matched_at is null;
