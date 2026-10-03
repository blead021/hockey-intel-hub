-- 0042: flag household names (top 15 F, 8 D, 4 G by projected WAR) so undervalued lists leave them out.

drop view player_perception;
create view player_perception as
with latest as (select max(date) as d from sentiment_daily),
fans as (
  select s.player_id, s.score_0_100::float8 as fans, s.window_mentions
  from sentiment_daily s, latest where s.date = latest.d and s.audience = 'fan' and s.score_0_100 is not null),
cur as (select max(season_id) as s from games where game_type = 2),
g as (select id from games, cur where game_type = 2 and season_id in (cur.s, cur.s - 10001)),
onice as (
  select o.player_id, sum(o.xgf)::float8 / nullif(sum(o.xgf) + sum(o.xga), 0) as xgf_pct
  from player_game_onice o join g on g.id = o.game_id where o.xgf is not null group by o.player_id),
gs as (
  select s.player_id, avg(s.game_score)::float8 as gs_pg, count(*) as gp
  from player_game_score s join g on g.id = s.game_id group by s.player_id),
val as (
  select distinct on (player_id) player_id, war_proj::float8 as war_proj, surplus::float8 as surplus
  from player_value order by player_id, as_of desc),
-- Household names: the league's top 15 forwards, 8 defensemen, and 4 goalies by projected WAR. Nobody
-- undervalues them, even when fans grumble, so they are left out of the undervalued lists.
stars as (
  select v.player_id,
         rank() over (partition by case when p.position = 'D' then 'D' when p.position = 'G' then 'G' else 'F' end
                      order by v.war_proj desc nulls last) as war_rank,
         case when p.position = 'D' then 8 when p.position = 'G' then 4 else 15 end as star_cutoff
  from val v join players p on p.id = v.player_id),
base as (
  select f.player_id, f.fans, f.window_mentions,
         case when p.position = 'D' then 'D' when p.position = 'G' then 'G' else 'F' end as grp,
         o.xgf_pct, v.war_proj, v.surplus, gs.gs_pg, gs.gp
  from fans f join players p on p.id = f.player_id
  left join onice o on o.player_id = f.player_id
  left join val v on v.player_id = f.player_id
  left join gs on gs.player_id = f.player_id
  where coalesce(gs.gp, 0) >= 20),
ranked as (
  select b.*,
         percent_rank() over (partition by grp order by fans) * 100 as fans_pct,
         -- goalies have no on-ice xGF%; their blend is WAR and Game Score
         (coalesce(percent_rank() over (partition by grp order by xgf_pct nulls first), 0) * (grp <> 'G')::int
          + percent_rank() over (partition by grp order by war_proj nulls first)
          + percent_rank() over (partition by grp order by gs_pg nulls first)) / (case when grp = 'G' then 2 else 3 end) * 100
           as perf_pct
  from base b)
select r.player_id, grp, fans, fans_pct, perf_pct, perf_pct - fans_pct as gap, xgf_pct, war_proj, surplus, gs_pg, gp,
       window_mentions, coalesce(st.war_rank <= st.star_cutoff, false) as star
from ranked r left join stars st on st.player_id = r.player_id;
