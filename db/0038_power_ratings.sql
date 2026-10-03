-- 0038: team power rating and buyer/seller status, for Trade Targets availability (Brian, 2026-10-03:
-- contenders do not trade their core players; early-season standings mean little, so blend in last season).
--
-- Rating per team = average of three z-scores across the league: points percentage, goal differential per
-- game, and 5v5 xGF%. This season's value is blended with last season's by games played:
-- weight on this season = gp / (gp + 20), so after 20 games it is half and after 60 games three quarters.
-- Status by rank: top 10 Contender, bottom 10 Seller, the 12 between Bubble.

create view team_power as
with cur as (select max(season_id) as s from games where game_type = 2),
stats as (
  select ts.team_id, ts.season_id, ts.gp,
         ts.points::float8 / nullif(2 * ts.gp, 0) as pts_pct,
         (ts.goals_for - ts.goals_against)::float8 / nullif(ts.gp, 0) as gd_pg,
         o.xgf::float8 / nullif(o.xgf + o.xga, 0) as xgf_pct
  from team_season_stats ts
  left join team_season_onice o on o.team_id = ts.team_id and o.season_id = ts.season_id and o.game_type = 2
  where ts.season_id in ((select s from cur), (select s from cur) - 10001)),
z as (
  select team_id, season_id, gp,
         ((pts_pct - avg(pts_pct) over w) / nullif(stddev_pop(pts_pct) over w, 0)
          + (gd_pg - avg(gd_pg) over w) / nullif(stddev_pop(gd_pg) over w, 0)
          + coalesce((xgf_pct - avg(xgf_pct) over w) / nullif(stddev_pop(xgf_pct) over w, 0), 0)) / 3 as rating
  from stats window w as (partition by season_id)),
blend as (
  select t.id as team_id,
         coalesce(c.gp, 0) as gp,
         coalesce(c.rating, 0) * coalesce(c.gp, 0)::float8 / (coalesce(c.gp, 0) + 20)
           + coalesce(l.rating, 0) * 20.0 / (coalesce(c.gp, 0) + 20) as rating
  from teams t cross join cur
  left join z c on c.team_id = t.id and c.season_id = cur.s
  left join z l on l.team_id = t.id and l.season_id = cur.s - 10001
  where t.active)
select team_id, gp, rating,
       rank() over (order by rating desc)::int as power_rank,
       case when rank() over (order by rating desc) <= 10 then 'Contender'
            when rank() over (order by rating desc) > 22 then 'Seller'
            else 'Bubble' end as status
from blend;
