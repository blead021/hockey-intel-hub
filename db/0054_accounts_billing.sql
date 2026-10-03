-- 0054: accounts and billing (Phase 6, CLAUDE.md sections 2 and 5). Users come from Clerk (auth_provider_id is the
-- Clerk user id); plan and subscription fields are set only by the Stripe webhook. Built before the Clerk and Stripe
-- accounts exist, so nothing writes here until they are connected.

create table users (
  id serial primary key,
  auth_provider_id text not null unique,
  email text,
  favorite_team_id smallint references teams (id),
  plan text not null default 'free' check (plan in ('free', 'pro')),
  subscription_status text,              -- Stripe's: active, trialing, past_due, canceled, unpaid, incomplete, ...
  stripe_customer_id text unique,
  stripe_subscription_id text,
  price_interval text check (price_interval in ('monthly', 'annual')),
  current_period_end timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Every Stripe event handled, so a retried delivery is never applied twice.
create table stripe_events (
  event_id text primary key,
  type text not null,
  processed_at timestamptz not null default now()
);

create table email_subscribers (
  email text primary key,
  user_id integer references users (id) on delete set null,
  weekly_digest boolean not null default true,
  unsubscribe_token uuid not null unique default gen_random_uuid(),
  subscribed_at timestamptz not null default now(),
  unsubscribed_at timestamptz
);

create table watchlists (
  user_id integer not null references users (id) on delete cascade,
  player_id integer not null references players (id),
  created_at timestamptz not null default now(),
  primary key (user_id, player_id)
);

-- Saved Trade Builder deals. The deal is the Builder's web address parameters (a, b, in, out, pin, pout, r);
-- share_id makes a link others can open.
create table trade_scenarios (
  id serial primary key,
  user_id integer not null references users (id) on delete cascade,
  share_id uuid not null unique default gen_random_uuid(),
  title text,
  deal jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table alerts (
  id serial primary key,
  user_id integer not null references users (id) on delete cascade,
  kind text not null check (kind in ('chatter_spike', 'contract', 'trade', 'injury')),
  player_id integer references players (id),
  team_id smallint references teams (id),
  active boolean not null default true,
  last_sent_at timestamptz,
  created_at timestamptz not null default now(),
  check (player_id is not null or team_id is not null)
);

create index alerts_player_idx on alerts (player_id) where active;
create index alerts_team_idx on alerts (team_id) where active;
