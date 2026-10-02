-- 0007: contracts kept current automatically from team announcements and news coverage.
-- Unknown details are stored as NULL (shown as "unknown"), never guessed.

alter table contracts alter column cap_hit drop not null;
alter table contracts alter column start_season drop not null;
alter table contracts alter column end_season drop not null;
alter table contracts alter column retained_pct drop not null;
alter table contracts alter column retained_pct drop default;
alter table contracts drop constraint contracts_player_name_start_season_key;

alter table contracts add column status text not null default 'active'
  check (status in ('active', 'bought_out', 'terminated'));
alter table contracts add column contract_type text
  check (contract_type in ('standard', 'entry_level', 'extension'));
alter table contracts add column signed_on date;
alter table contracts add column source text not null default 'starting_file'
  check (source in ('starting_file', 'news'));
alter table contracts add column updated_at timestamptz not null default now();

-- Contracts already loaded had retained_pct 0 because 0001 defaulted it; keep that as a known 0.
create unique index contracts_player_start_idx on contracts (player_id, start_season)
  where player_id is not null and start_season is not null;

-- Every news item the job has looked at, so nothing is read or paid for twice.
create table contract_news (
  id text primary key,                 -- stable key from headline and outlet
  title text not null,
  outlet text,
  url text,
  published_at timestamptz,
  query text,
  status text not null default 'pending'
    check (status in ('pending', 'skipped', 'extracted', 'failed')),
  processed_at timestamptz,
  error text,
  collected_at timestamptz not null default now()
);

create index contract_news_status_idx on contract_news (status, published_at);

-- One row per transaction found in the news, applied or not, with the reason.
create table contract_events (
  id bigserial primary key,
  job_run_id bigint references job_runs (id),
  event_type text not null,
  event_status text not null,          -- completed, reported, or rumor (only completed is applied)
  player_name text not null,
  player_id integer references players (id),
  details jsonb not null,              -- everything the model extracted, unknowns as null
  news_ids text[] not null,            -- contract_news rows it came from
  source_urls text[] not null,
  outcome text not null,               -- applied, no_change, skipped_unconfirmed, skipped_unmatched, skipped_type
  outcome_note text,
  model text,
  created_at timestamptz not null default now()
);

-- Every field the job changes: what, from what, to what, and where it came from.
create table contract_changes (
  id bigserial primary key,
  event_id bigint not null references contract_events (id),
  contract_id integer references contracts (id),
  player_id integer references players (id),
  action text not null check (action in ('create', 'update')),
  field text not null,
  old_value text,
  new_value text,
  source_urls text[] not null,
  changed_at timestamptz not null default now()
);

create index contract_changes_changed_idx on contract_changes (changed_at desc);

insert into data_sources (key, name, enabled, notes) values
  ('contract_news', 'Contract updates from team announcements and news (Claude)', true,
   'Reads Google News headlines and summaries, never contract database sites or full articles.')
on conflict (key) do nothing;
