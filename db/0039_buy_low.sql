-- 0039: buy-low inputs (Brian, 2026-10-03: buy-low should not just list the best players). A buy-low skater
-- plays well underneath but his results lag, usually because of luck that tends to even out: his underlying
-- percentile (5v5 xGF% and own chance quality, ixG per 60) is well above his results percentile (points per
-- 60), with poor luck (on-ice PDO under 99, or fewer goals than his chances deserve). Percentiles are within
-- position group, over this season and last together so early-season games do not dominate.

create view player_buy_low as
with cur as (select max(season_id) as s from games where game_type = 2),
g as (select id from games, cur where game_type = 2 and season_id in (cur.s, cur.s - 10001)),
box as (
  select s.player_id, sum(s.toi_sec)::float8 as toi, sum(s.g + s.a1 + s.a2)::float8 as pts, count(*) as gp
  from game_skater_stats s join g on g.id = s.game_id group by s.player_id
  having sum(s.toi_sec) >= 30000),
onice as (
  select o.player_id, sum(o.xgf)::float8 as xgf, sum(o.xga)::float8 as xga, sum(o.gf)::float8 as gf,
         sum(o.ga)::float8 as ga, sum(o.sf)::float8 as sf, sum(o.sa)::float8 as sa
  from player_game_onice o join g on g.id = o.game_id where o.xgf is not null group by o.player_id),
shots as (
  select sh.player_id, sum(sh.goals)::float8 as goals, sum(sh.ixg)::float8 as ixg
  from player_game_shooting sh join g on g.id = sh.game_id group by sh.player_id),
rates as (
  select b.player_id, case when p.position = 'D' then 'D' else 'F' end as grp,
         b.pts * 3600 / b.toi as pts60,
         o.xgf / nullif(o.xgf + o.xga, 0) as xgf_pct,
         coalesce(s.ixg, 0) * 3600 / b.toi as ixg60,
         100 * (o.gf / nullif(o.sf, 0) + 1 - o.ga / nullif(o.sa, 0)) as pdo,
         coalesce(s.goals, 0) - coalesce(s.ixg, 0) as goals_minus_xg
  from box b join players p on p.id = b.player_id and p.position <> 'G'
  join onice o on o.player_id = b.player_id left join shots s on s.player_id = b.player_id),
ranked as (
  select r.*,
         (percent_rank() over (partition by grp order by xgf_pct) + percent_rank() over (partition by grp order by ixg60)) * 50
           as underlying_pct,
         percent_rank() over (partition by grp order by pts60) * 100 as results_pct
  from rates r where xgf_pct is not null)
select player_id, grp, underlying_pct, results_pct, pdo, goals_minus_xg,
       underlying_pct >= 55 and underlying_pct - results_pct >= 20 and (pdo < 99 or goals_minus_xg < -2) as buy_low
from ranked;
