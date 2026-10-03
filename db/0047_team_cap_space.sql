-- 0047: team cap space with LTIR relief. A team may exceed the ceiling by up to the cap hits of its players on
-- long-term injured reserve, so cap sheets show such a team at no space "using LTIR relief", not negative.
-- Simplified: relief = the part of the overage the LTIR cap hits cover (the CBA's exact relief depends on the
-- team's space on the day of placement, which is not tracked). Regular IR gives no relief.

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
