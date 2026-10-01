-- 0001: core reference tables, data source switches, and job logging.

create table teams (
  id smallint primary key,             -- NHL team id
  abbrev text not null unique,          -- e.g. VAN
  name text not null,
  conference text check (conference in ('Eastern', 'Western')),
  division text,
  active boolean not null default true
);

create table seasons (
  id integer primary key,               -- NHL format, e.g. 20262027
  start_date date,
  end_date date,
  regular_season_games smallint not null default 82
);

create table cap_limits (
  season_id integer primary key references seasons (id),
  cap_ceiling bigint not null,
  cap_floor bigint
);

create table players (
  id integer primary key,               -- NHL player id
  first_name text not null,
  last_name text not null,
  birth_date date,
  position text check (position in ('C', 'L', 'R', 'D', 'G')),
  shoots text check (shoots in ('L', 'R')),
  height_in smallint,
  weight_lb smallint,
  current_team_id smallint references teams (id),
  active boolean not null default true,
  updated_at timestamptz not null default now()
);

create index players_current_team_idx on players (current_team_id);

-- Every alternate name, nickname, and source-specific id, mapped to one NHL player id.
create table player_aliases (
  id bigserial primary key,
  player_id integer not null references players (id) on delete cascade,
  alias text not null,
  kind text not null check (kind in ('name', 'nickname', 'source_id')),
  source text not null default 'any',   -- 'any' for names, or the source key for ids
  created_at timestamptz not null default now(),
  unique (player_id, source, alias)
);

create index player_aliases_alias_idx on player_aliases (lower(alias));

create table games (
  id integer primary key,               -- NHL game id
  season_id integer not null references seasons (id),
  game_type smallint not null,          -- 1 preseason, 2 regular season, 3 playoffs
  game_date date not null,
  start_time_utc timestamptz,
  home_team_id smallint not null references teams (id),
  away_team_id smallint not null references teams (id),
  home_score smallint,
  away_score smallint,
  state text,                           -- NHL gameState, e.g. FUT, LIVE, OFF
  updated_at timestamptz not null default now()
);

create index games_date_idx on games (game_date);
create index games_season_idx on games (season_id);

-- On/off switch for every external source. Brian confirms commercial use before launch.
-- When a source is off, its section of the app is hidden or marked unavailable.
create table data_sources (
  key text primary key,
  name text not null,
  enabled boolean not null default false,
  commercial_use_confirmed boolean not null default false,
  notes text,
  updated_at timestamptz not null default now()
);

insert into data_sources (key, name, enabled, notes) values
  ('nhl_api',          'NHL API (api-web.nhle.com, api.nhle.com)', true,  'Unofficial and undocumented. Endpoints change without notice.'),
  ('nhl_edge',         'NHL EDGE player tracking',                 true,  'Endpoints to be discovered and documented in pipeline/ingest/README.md.'),
  ('moneypuck',        'MoneyPuck shot-level xG',                  true,  'Check terms, may be personal use only. Replaced later by our own xG model.'),
  ('contracts_csv',    'Contracts (manual CSV from PuckPedia or CapWages)', true, 'Manually maintained import.'),
  ('hockeystatcards',  'HockeyStatCards post-game cards (Gmail)',  true,  'Commercial use needs HockeyStatCards permission. Computed Game Score is the fallback.'),
  ('reddit',           'Reddit (official API)',                    true,  'r/hockey plus 32 team subreddits.'),
  ('bluesky',          'Bluesky (AT Protocol)',                    true,  'Curated beat writers and insiders plus keyword search.'),
  ('youtube',          'YouTube Data API comments',                true,  'Stay within the free daily quota.'),
  ('news_rss',         'News RSS (Google News, beat writers)',     true,  'Headline, snippet, URL, and date only.'),
  ('evolving_hockey',  'Evolving-Hockey WAR/GAR',                  false, 'Paid. Ask Brian before enabling.'),
  ('all_three_zones',  'All Three Zones',                          false, 'Paid. Ask Brian before enabling.');

-- One row per scheduled job run, with counts such as games loaded or mentions collected.
create table job_runs (
  id bigserial primary key,
  job text not null,
  status text not null default 'running' check (status in ('running', 'success', 'failed')),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  counts jsonb not null default '{}'::jsonb,
  error text
);

create index job_runs_job_started_idx on job_runs (job, started_at desc);

-- Current season plus the three prior seasons used for backfill.
insert into seasons (id) values (20232024), (20242025), (20252026), (20262027);

insert into cap_limits (season_id, cap_ceiling) values (20262027, 104000000);
