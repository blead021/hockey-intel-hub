-- 0002: sentiment collection (Phase 1). Raw mentions only; scoring comes in Phase 4.

-- What the collectors watch: subreddits, Bluesky accounts and searches, news feeds, YouTube channels.
-- Edited through pipeline/sentiment/feeds.csv, then loaded with `python -m pipeline.sentiment.feeds`.
create table sentiment_feeds (
  id serial primary key,
  kind text not null check (kind in (
    'subreddit', 'bluesky_account', 'bluesky_search', 'rss', 'google_news', 'youtube_channel')),
  value text not null,                  -- subreddit name, Bluesky handle, search text, feed URL, or YouTube handle
  label text,
  team_id smallint references teams (id),
  audience text not null check (audience in ('fan', 'beat_writer', 'media')),
  active boolean not null default true,
  notes text,
  updated_at timestamptz not null default now(),
  unique (kind, value)
);

-- Where each feed left off, so the next run only asks for newer items.
create table collector_state (
  feed_id integer primary key references sentiment_feeds (id) on delete cascade,
  cursor text,                          -- source-specific JSON, e.g. newest timestamp collected
  last_run_at timestamptz,
  last_success_at timestamptz,
  last_error text,
  consecutive_failures integer not null default 0
);

create table mentions (
  id bigserial primary key,
  source text not null check (source in ('reddit', 'bluesky', 'youtube', 'news_rss')),
  source_item_id text not null,         -- the source's own id, used to skip duplicates
  feed_id integer references sentiment_feeds (id) on delete set null,
  kind text not null check (kind in ('post', 'comment', 'article')),
  audience text not null check (audience in ('fan', 'beat_writer', 'media')),
  team_id smallint references teams (id),   -- team context from the feed, not a player match
  url text,
  author text,
  posted_at timestamptz not null,
  title text,                           -- post title, video title, or headline
  text text,                            -- body; for news, a short snippet only
  thread_id text,                       -- Reddit post or YouTube video a comment belongs to
  raw jsonb not null default '{}'::jsonb,   -- a few useful fields; the full response is in R2
  archive_key text,                     -- R2 object holding the full response
  collected_at timestamptz not null default now(),
  unique (source, source_item_id)
);

create index mentions_posted_idx on mentions (posted_at desc);
create index mentions_team_posted_idx on mentions (team_id, posted_at desc);
