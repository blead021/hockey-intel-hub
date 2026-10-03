-- 0037: larger samples for need percentiles (300 minutes overall, 60 on the power play or penalty kill).

create or replace view player_need_pctiles as
with latest as (
  -- Most recent season with 300+ minutes, so a short stretch cannot top the list.
  select distinct on (player_id) *
  from player_style_traits where toi >= 18000 order by player_id, season_id desc),
scoring as (
  select l.player_id, percent_rank() over (partition by l.season_id, l.grp order by l.g::float8 / nullif(l.toi, 0)) * 100 as p
  from latest l),
special as (
  select o.player_id, g.season_id,
         sum(o.pp_xgf)::float8 / nullif(sum(s.pp_toi_sec), 0) * 3600 as pp_rate, sum(s.pp_toi_sec) as pp_toi,
         sum(o.sh_xga)::float8 / nullif(sum(s.pk_toi_sec), 0) * 3600 as pk_rate, sum(s.pk_toi_sec) as pk_toi
  from player_game_onice o
  join game_skater_stats s on s.player_id = o.player_id and s.game_id = o.game_id
  join games g on g.id = o.game_id
  where g.game_type = 2 group by o.player_id, g.season_id),
special_ranked as (
  select sp.player_id,
         case when sp.pp_toi >= 3600 then percent_rank() over (partition by sp.season_id, sp.pp_toi >= 3600 order by sp.pp_rate) * 100 end as pp,
         case when sp.pk_toi >= 3600 then percent_rank() over (partition by sp.season_id, sp.pk_toi >= 3600 order by sp.pk_rate desc) * 100 end as pk
  from special sp join latest l on l.player_id = sp.player_id and l.season_id = sp.season_id),
goalies as (
  select v.player_id, percent_rank() over (order by v.war_proj) * 100 as p
  from (select distinct on (player_id) player_id, war_proj from player_value order by player_id, as_of desc) v
  join players p on p.id = v.player_id where p.position = 'G' and v.war_proj is not null)
select l.player_id,
       sc.p as goal_scoring,
       l.p_playmaking * 100 as playmaking,
       l.p_physical * 100 as physicality,
       l.p_defense * 100 as defense_5v5,
       sr.pp as power_play,
       sr.pk as penalty_kill,
       null::float8 as goaltending
from latest l
left join scoring sc on sc.player_id = l.player_id
left join special_ranked sr on sr.player_id = l.player_id
union all
select player_id, null, null, null, null, null, null, p from goalies;
