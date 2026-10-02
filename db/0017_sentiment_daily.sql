-- 0017: daily sentiment per player and audience (CLAUDE.md section 6).
-- score_0_100 = 50 + 50 x recency-weighted mean sentiment over the last 28 days (half-life 7 days),
-- shown only when the window holds at least the minimum number of scored mentions.

create table sentiment_daily (
  player_id integer not null references players (id),
  date date not null,
  audience text not null check (audience in ('fan', 'beat_writer', 'media', 'all')),
  score_0_100 numeric(5, 2),            -- null when too few mentions to show
  n_mentions integer not null,          -- scored mentions posted that day
  window_mentions integer not null,     -- scored mentions in the 28-day window
  trade_mentions integer not null,      -- trade-related mentions posted that day
  primary key (player_id, date, audience)
);

create index sentiment_daily_date_idx on sentiment_daily (date, audience);

-- Trade chatter and spikes per player, as of each date (all audiences together).
-- chatter_7d: trade-related mentions in the last 7 days. spike: chatter_7d is at least twice the
-- weekly average of the 4 weeks before, and at least 3 mentions.
create view trade_chatter as
with daily as (
  select player_id, date, sum(trade_mentions) as trade_mentions
  from sentiment_daily where audience <> 'all'
  group by player_id, date
),
windows as (
  select d.player_id, d.date,
         (select coalesce(sum(x.trade_mentions), 0) from daily x
           where x.player_id = d.player_id and x.date > d.date - 7 and x.date <= d.date) as chatter_7d,
         (select coalesce(sum(x.trade_mentions), 0) from daily x
           where x.player_id = d.player_id and x.date > d.date - 35 and x.date <= d.date - 7) / 4.0 as prior_weekly_avg
  from daily d
)
select player_id, date, chatter_7d, prior_weekly_avg,
       chatter_7d >= 3 and chatter_7d >= 2 * prior_weekly_avg as spike
from windows;
