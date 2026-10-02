-- 0021: Play style trait percentiles as one view (CLAUDE.md section 6), shared by the website and the
-- Claude write-up job, plus batch tracking for the write-ups and their on/off switch.

create view player_style_traits as
with base as (
  select g.season_id, s.player_id,
         case when p.position = 'D' then 'D' when p.position = 'C' then 'C' else 'W' end as grp,
         sum(s.toi_sec)::float8 as toi, count(*)::int as gp,
         sum(s.g)::int as g, sum(s.a1 + s.a2)::int as a,
         sum(s.a1)::float8 as a1, sum(s.hits + s.blocks)::float8 as physical,
         sum(s.takeaways - s.giveaways)::float8 as puck
  from game_skater_stats s join games g on g.id = s.game_id join players p on p.id = s.player_id
  where g.game_type = 2
  group by g.season_id, s.player_id, grp
  having sum(s.toi_sec) >= 6000),
shots as (
  select g.season_id, sh.player_id, sum(sh.shots)::float8 as shots
  from player_game_shooting sh join games g on g.id = sh.game_id
  where g.game_type = 2 group by 1, 2),
style as (
  select g.season_id, st.player_id, sum(st.oz_hits + st.oz_takeaways)::float8 as forecheck,
         sum(st.rush_onice_5v5)::float8 as rush,
         sum(st.shots_slot)::int as slot, sum(st.shots_mid)::int as mid, sum(st.shots_perimeter)::int as perimeter
  from player_game_style st join games g on g.id = st.game_id
  where g.game_type = 2 group by 1, 2),
onice as (
  select g.season_id, o.player_id, sum(o.toi_5v5_sec)::float8 as toi5, sum(o.xga)::float8 as xga,
         sum(t.toi_5v5_sec - o.toi_5v5_sec)::float8 as off_toi5, sum(t.xga - o.xga)::float8 as off_xga
  from player_game_onice o join team_game_onice t on t.team_id = o.team_id and t.game_id = o.game_id
  join games g on g.id = o.game_id
  where g.game_type = 2 and o.xga is not null group by 1, 2),
edge as (
  select season_id, player_id, top_speed_pctile::float8 as top_pct,
         bursts_20plus::float8 / nullif(games_played, 0) as bursts_pg
  from edge_player_stats),
rates as (
  select b.season_id, b.player_id, b.grp, b.gp, b.g, b.a, b.toi,
         coalesce(sh.shots, 0) * 3600 / b.toi as shooting,
         b.a1 * 3600 / b.toi as playmaking,
         st.rush * 3600 / nullif(oi.toi5, 0) as entries,
         st.forecheck * 3600 / b.toi as forecheck,
         b.physical * 3600 / b.toi as physical,
         oi.xga * 3600 / nullif(oi.toi5, 0) - oi.off_xga * 3600 / nullif(oi.off_toi5, 0) as rel_xga60,
         b.puck * 3600 / b.toi as puck,
         e.top_pct, e.bursts_pg,
         coalesce(st.slot, 0) as slot, coalesce(st.mid, 0) as mid, coalesce(st.perimeter, 0) as perimeter
  from base b
  left join shots sh on sh.season_id = b.season_id and sh.player_id = b.player_id
  left join style st on st.season_id = b.season_id and st.player_id = b.player_id
  left join onice oi on oi.season_id = b.season_id and oi.player_id = b.player_id
  left join edge e on e.season_id = b.season_id and e.player_id = b.player_id)
select r.season_id, r.player_id, r.grp, r.gp, r.g, r.a, r.toi, r.slot, r.mid, r.perimeter,
  percent_rank() over (partition by season_id, grp order by shooting) as p_shooting,
  percent_rank() over (partition by season_id, grp order by playmaking) as p_playmaking,
  case when entries is not null then percent_rank() over (partition by season_id, grp, entries is null order by entries) end as p_entries,
  case when forecheck is not null then percent_rank() over (partition by season_id, grp, forecheck is null order by forecheck) end as p_forecheck,
  percent_rank() over (partition by season_id, grp order by physical) as p_physical,
  case when rel_xga60 is not null then percent_rank() over (partition by season_id, grp, rel_xga60 is null order by rel_xga60 desc) end as p_defense,
  percent_rank() over (partition by season_id, grp order by puck) as p_puck,
  case when bursts_pg is not null then
    (top_pct + percent_rank() over (partition by season_id, grp, bursts_pg is null order by bursts_pg)) / 2 end as p_speed
from rates r;

create table play_style_batches (
  id text primary key,                  -- Anthropic batch id
  model text not null,
  player_seasons jsonb not null,        -- custom_id -> [player_id, season_id]
  requests integer not null,
  status text not null default 'submitted',  -- submitted, applied
  submitted_at timestamptz not null default now(),
  applied_at timestamptz,
  input_tokens integer,
  output_tokens integer
);

insert into data_sources (key, name, enabled, notes) values
  ('play_style_writing', 'Play style write-ups with Claude (claude-haiku-4-5, Message Batches)', true,
   'Paid, about $2-4 per month. Weekly archetype, scouting summary, tags, strengths, and watch-outs per skater.')
on conflict (key) do nothing;
