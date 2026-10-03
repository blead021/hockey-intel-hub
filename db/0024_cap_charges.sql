-- 0024: count every contract a team holds against its cap, not only players on the NHL roster list.
-- The NHL roster feed leaves out injured players and players in the minors, so cap totals were too low.

alter table cap_limits add column min_salary integer;
update cap_limits set min_salary = case season_id
  when 20222023 then 750000 when 20232024 then 775000 when 20242025 then 775000
  when 20252026 then 775000 when 20262027 then 850000 end;

-- Current season cap charges by team. kind:
--   roster   on the team's NHL roster: full cap hit (after any salary another team retained)
--   injured  off the roster but an NHL regular (40+ games last season or this season), likely injured: full
--   buried   off the roster otherwise (minors, juniors, Europe): only the part above the buried allowance,
--            league minimum salary + $375,000 (CBA). An estimate, since there is no public injury feed.
--   retained salary this team kept on a player it traded away
create view team_cap_charges as
with cur as (
  select max(season_id) as season_id from games where game_type = 2),
lim as (
  select l.season_id, l.cap_ceiling, coalesce(l.min_salary, 0) + 375000 as buried_allowance
  from cap_limits l join cur using (season_id)),
gp as (
  select s.player_id, count(*) filter (where g.season_id = (select season_id from cur)) as gp_now,
         count(*) filter (where g.season_id = (select season_id from cur) - 10001) as gp_last
  from game_skater_stats s join games g on g.id = s.game_id
  where g.game_type = 2 and g.season_id >= (select season_id from cur) - 10001
  group by s.player_id
  union all
  select s.player_id, count(*) filter (where g.season_id = (select season_id from cur)),
         count(*) filter (where g.season_id = (select season_id from cur) - 10001)
  from game_goalie_stats s join games g on g.id = s.game_id
  where g.game_type = 2 and g.season_id >= (select season_id from cur) - 10001
  group by s.player_id),
held as (
  select c.id as contract_id, c.player_id, coalesce(p.first_name || ' ' || p.last_name, c.player_name) as name,
         c.team_id, c.cap_hit * (1 - coalesce(c.retained_pct, 0) / 100) as charged,
         p.current_team_id = c.team_id as on_roster,
         coalesce((select max(greatest(gp_now, gp_last)) from gp where gp.player_id = c.player_id), 0) >= 40 as regular
  from contracts c left join players p on p.id = c.player_id, cur
  where c.status = 'active' and cur.season_id between coalesce(c.start_season, 0) and c.end_season)
select h.team_id, h.contract_id, h.player_id, h.name,
       case when h.on_roster then 'roster' when h.regular then 'injured' else 'buried' end as kind,
       case when h.on_roster or h.regular then h.charged
            else greatest(h.charged - lim.buried_allowance, 0) end as charge
from held h, lim
union all
select c.retained_by, c.id, c.player_id, coalesce(p.first_name || ' ' || p.last_name, c.player_name), 'retained',
       c.cap_hit * c.retained_pct / 100
from contracts c left join players p on p.id = c.player_id, cur
where c.retained_pct > 0 and c.retained_by is not null and c.status = 'active'
  and cur.season_id between coalesce(c.start_season, 0) and c.end_season;
