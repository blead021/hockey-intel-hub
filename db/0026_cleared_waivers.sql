-- 0026: a player placed on waivers who is on no NHL roster two days later cleared and went to the minors.

drop view team_cap_charges;
create view team_cap_charges as
with cur as (
  select max(season_id) as season_id from games where game_type = 2),
lim as (
  select l.season_id, l.cap_ceiling, coalesce(l.min_salary, 0) + 375000 as buried_allowance
  from cap_limits l join cur using (season_id)),
gp as (
  select player_id, sum(n) as n from (
    select s.player_id, count(*) as n from game_skater_stats s join games g on g.id = s.game_id
    where g.game_type = 2 and g.season_id >= (select season_id from cur) - 10001 group by 1, g.season_id
    union all
    select s.player_id, count(*) from game_goalie_stats s join games g on g.id = s.game_id
    where g.game_type = 2 and g.season_id >= (select season_id from cur) - 10001 group by 1, g.season_id) x
  group by player_id having max(n) >= 40),
held as (
  select c.id as contract_id, c.player_id, coalesce(p.first_name || ' ' || p.last_name, c.player_name) as name,
         c.team_id, c.cap_hit * (1 - coalesce(c.retained_pct, 0) / 100) as charged,
         case
           when p.current_team_id = c.team_id then 'roster'
           when st.status = 'ir' then 'injured'
           when st.status = 'ltir' then 'ltir'
           -- Waivers last 24 hours; a claimed player appears on his new team's roster. Still off every
           -- roster two days later means he cleared and was sent down.
           when st.status = 'waivers' and st.since < current_date - 2 then 'buried'
           when st.status = 'waivers' then 'waivers'
           when st.status = 'minors' then 'buried'
           when st.status = 'nhl' then 'injured'      -- listed as NHL but missing from the roster feed: IR
           else 'unknown'
         end as kind,
         c.player_id in (select player_id from gp) as regular
  from contracts c left join players p on p.id = c.player_id
  left join player_status st on st.player_id = c.player_id, cur
  where c.status = 'active' and cur.season_id between coalesce(c.start_season, 0) and c.end_season)
select h.team_id, h.contract_id, h.player_id, h.name, h.kind,
       case
         when h.kind in ('roster', 'injured', 'ltir', 'waivers') then h.charged
         when h.kind = 'unknown' and h.regular then h.charged
         else greatest(h.charged - lim.buried_allowance, 0)
       end as charge
from held h, lim
union all
select c.retained_by, c.id, c.player_id, coalesce(p.first_name || ' ' || p.last_name, c.player_name), 'retained',
       c.cap_hit * c.retained_pct / 100
from contracts c left join players p on p.id = c.player_id, cur
where c.retained_pct > 0 and c.retained_by is not null and c.status = 'active'
  and cur.season_id between coalesce(c.start_season, 0) and c.end_season;
