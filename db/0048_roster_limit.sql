-- 0048: at most 23 players count as on a team's NHL roster. The NHL roster feed lags when players are sent
-- down, which listed up to 27 players for some teams. Extras beyond 23 (fewest games this season, then lowest cap
-- hit, top two goalies kept) count as sent to the minors.

drop view team_cap_space;
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
season_gp as (
  select player_id, count(*) as n from (
    select s.player_id from game_skater_stats s join games g on g.id = s.game_id, cur
    where g.game_type = 2 and g.season_id = cur.season_id
    union all
    select s.player_id from game_goalie_stats s join games g on g.id = s.game_id, cur
    where g.game_type = 2 and g.season_id = cur.season_id) x
  group by player_id),
-- NHL teams carry at most 23 players, but the NHL roster feed is slow to drop players sent to the minors.
-- When a team's feed lists more than 23, the players who have dressed least this season, cheapest first, are
-- the extras; they count as sent down. The top two goalies always stay.
roster_rank as (
  select c.id as contract_id,
         row_number() over (partition by c.team_id order by coalesce(sg.n, 0) desc, c.cap_hit desc) as n,
         case when p.position = 'G' then row_number() over (partition by c.team_id, p.position = 'G'
              order by coalesce(sg.n, 0) desc, c.cap_hit desc) end as goalie_n
  from contracts c join players p on p.id = c.player_id left join season_gp sg on sg.player_id = c.player_id, cur
  where c.status = 'active' and p.current_team_id = c.team_id
    and cur.season_id between coalesce(c.start_season, 0) and c.end_season),
held as (
  select c.id as contract_id, c.player_id, coalesce(p.first_name || ' ' || p.last_name, c.player_name) as name,
         c.team_id, c.cap_hit * (1 - coalesce(c.retained_pct, 0) / 100) as charged,
         case
           when p.current_team_id = c.team_id and (rr.n <= 23 or rr.goalie_n <= 2) then 'roster'
           when p.current_team_id = c.team_id then 'buried'
           when st.status = 'ir' then 'injured'
           when st.status = 'ltir' then 'ltir'
           -- Waivers last 24 hours; a claimed player appears on his new team's roster. Still off every
           -- roster two days later means he cleared and was sent down.
           when st.status = 'waivers' and st.since < current_date - 2 then 'buried'
           when st.status = 'waivers' then 'waivers'
           when st.status = 'minors' then 'buried'
           -- Listed as NHL but missing from the roster feed: on IR. Only news from this training camp on counts;
           -- an older recall says nothing about today.
           when st.status = 'nhl' and st.since >= make_date(cur.season_id / 10000, 9, 1) then 'injured'
           else 'unknown'
         end as kind,
         c.player_id in (select player_id from gp) as regular,
         st.cap_charge as special_charge
  from contracts c left join players p on p.id = c.player_id
  left join player_status st on st.player_id = c.player_id
  left join roster_rank rr on rr.contract_id = c.id, cur
  where c.status = 'active' and cur.season_id between coalesce(c.start_season, 0) and c.end_season)
select h.team_id, h.contract_id, h.player_id, h.name, h.kind,
       case
         -- A special charge set from a reported cap rule (for example a two-way player starting the season on
         -- IR, whose charge is prorated by last season's NHL roster time) replaces the usual amount.
         when h.special_charge is not null and h.kind <> 'roster' then h.special_charge
         when h.kind in ('roster', 'injured', 'ltir', 'waivers') then h.charged
         -- No news yet: NHL regulars, and contracts of $3M or more (teams almost never bury those), are
         -- most likely injured, so they count in full; anyone else is assumed to be in the minors.
         when h.kind = 'unknown' and (h.regular or h.charged >= 3000000) then h.charged
         else greatest(h.charged - lim.buried_allowance, 0)
       end as charge
from held h, lim
union all
select c.retained_by, c.id, c.player_id, coalesce(p.first_name || ' ' || p.last_name, c.player_name), 'retained',
       c.cap_hit * c.retained_pct / 100
from contracts c left join players p on p.id = c.player_id, cur
where c.retained_pct > 0 and c.retained_by is not null and c.status = 'active'
  and cur.season_id between coalesce(c.start_season, 0) and c.end_season
union all
-- Buyouts, bonus overages, and other dead cap recorded from news (amount null when not yet reported).
select a.team_id, null::bigint, a.player_id, coalesce(a.player_name, a.kind), 'adjustment:' || a.kind, coalesce(a.amount, 0)
from team_cap_adjustments a, cur
where a.season_id = cur.season_id;

create view team_cap_space as
with cur as (select max(season_id) as s from games where game_type = 2),
ceiling as (select cap_ceiling::float8 as c from cap_limits, cur where season_id = cur.s),
totals as (
  select t.id as team_id,
         coalesce(sum(x.charge), 0)::float8 as charges,
         coalesce(sum(x.charge) filter (where x.kind = 'ltir'), 0)::float8 as ltir
  from teams t left join team_cap_charges x on x.team_id = t.id
  where t.active group by t.id)
select t.team_id, t.charges, t.ltir, ceiling.c as ceiling,
       least(t.ltir, greatest(t.charges - ceiling.c, 0)) as ltir_relief,
       ceiling.c - t.charges + least(t.ltir, greatest(t.charges - ceiling.c, 0)) as space
from totals t, ceiling;
