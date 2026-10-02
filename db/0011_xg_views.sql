-- 0011: season views for expected goals, plus the season adjustment.
-- xg_season_factor scales a season's xG so its league total equals actual goals (regular season,
-- unblocked shots). Multiply any xG figure by its season's factor before showing it.

create view xg_season_factor as
select g.season_id,
       sum(s.goals) as goals,
       sum(s.ixg) as xg,
       coalesce(sum(s.goals) / nullif(sum(s.ixg), 0), 1) as factor
from player_game_shooting s
join games g on g.id = s.game_id
where g.game_type = 2
group by g.season_id;

-- New columns go at the end so the existing view can be replaced in place.
create or replace view skater_season_onice as
select
  o.player_id,
  g.season_id,
  g.game_type,
  o.team_id,
  count(*) as gp,
  sum(o.toi_5v5_sec) as toi_5v5_sec,
  sum(o.cf) as cf, sum(o.ca) as ca,
  sum(o.ff) as ff, sum(o.fa) as fa,
  sum(o.sf) as sf, sum(o.sa) as sa,
  sum(o.gf) as gf, sum(o.ga) as ga,
  sum(o.oz_starts) as oz_starts, sum(o.nz_starts) as nz_starts, sum(o.dz_starts) as dz_starts,
  sum(t.cf - o.cf) as off_cf, sum(t.ca - o.ca) as off_ca,
  sum(t.ff - o.ff) as off_ff, sum(t.fa - o.fa) as off_fa,
  sum(t.gf - o.gf) as off_gf, sum(t.ga - o.ga) as off_ga,
  sum(o.xgf) as xgf, sum(o.xga) as xga,
  sum(o.hdcf) as hdcf, sum(o.hdca) as hdca,
  sum(t.xgf - o.xgf) as off_xgf, sum(t.xga - o.xga) as off_xga
from player_game_onice o
join team_game_onice t on t.team_id = o.team_id and t.game_id = o.game_id
join games g on g.id = o.game_id
group by o.player_id, g.season_id, g.game_type, o.team_id;

create or replace view team_season_onice as
select
  t.team_id,
  g.season_id,
  g.game_type,
  count(*) as gp,
  sum(t.toi_5v5_sec) as toi_5v5_sec,
  sum(t.cf) as cf, sum(t.ca) as ca,
  sum(t.ff) as ff, sum(t.fa) as fa,
  sum(t.sf) as sf, sum(t.sa) as sa,
  sum(t.gf) as gf, sum(t.ga) as ga,
  sum(t.xgf) as xgf, sum(t.xga) as xga,
  sum(t.hdcf) as hdcf, sum(t.hdca) as hdca
from team_game_onice t
join games g on g.id = t.game_id
group by t.team_id, g.season_id, g.game_type;

create view skater_season_shooting as
select s.player_id, g.season_id, g.game_type, s.team_id, count(*) as gp,
       sum(s.shots) as shots, sum(s.goals) as goals, sum(s.ixg) as ixg,
       sum(s.shots_5v5) as shots_5v5, sum(s.goals_5v5) as goals_5v5, sum(s.ixg_5v5) as ixg_5v5
from player_game_shooting s
join games g on g.id = s.game_id
group by s.player_id, g.season_id, g.game_type, s.team_id;

create view goalie_season_xg as
select x.player_id, g.season_id, g.game_type, x.team_id, count(*) as gp,
       sum(x.shots_faced) as shots_faced, sum(x.goals_against) as goals_against, sum(x.xga) as xga
from goalie_game_xg x
join games g on g.id = x.game_id
group by x.player_id, g.season_id, g.game_type, x.team_id;
