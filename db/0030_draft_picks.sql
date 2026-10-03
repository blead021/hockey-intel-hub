-- 0030: future draft picks and who owns them, for the Trade Builder (CLAUDE.md section 7).
-- Every team starts owning its own picks; pick trades found in news move them (pipeline/contracts/apply.py).

create table draft_picks (
  id serial primary key,
  draft_year smallint not null,
  round smallint not null check (round between 1 and 7),
  original_team_id smallint not null references teams (id),
  owner_team_id smallint not null references teams (id),
  condition text,                         -- as reported, for example "top-10 protected"; null if none reported
  last_moved date,                        -- date of the news that last moved it
  unique (draft_year, round, original_team_id)
);

create table draft_pick_moves (
  id bigserial primary key,
  pick_id integer not null references draft_picks (id),
  from_team_id smallint references teams (id),
  to_team_id smallint not null references teams (id),
  moved_on date not null,
  event_id bigint references contract_events (id),
  source_urls text[],
  created_at timestamptz not null default now()
);

insert into draft_picks (draft_year, round, original_team_id, owner_team_id)
select y, r, t.id, t.id
from teams t, generate_series(2027, 2029) as y, generate_series(1, 7) as r
where t.active
on conflict do nothing;
