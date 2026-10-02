-- 0009: season 5v5 on-ice totals per player and team, with off-ice totals for relative stats.
-- Off-ice = the team's 5v5 totals in the games the player played, minus his own on-ice totals.
-- Percentages, per-60 rates, and relative values are computed by the app from these sums.

create view skater_season_onice as
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
  sum(t.gf - o.gf) as off_gf, sum(t.ga - o.ga) as off_ga
from player_game_onice o
join team_game_onice t on t.team_id = o.team_id and t.game_id = o.game_id
join games g on g.id = o.game_id
group by o.player_id, g.season_id, g.game_type, o.team_id;

create view team_season_onice as
select
  t.team_id,
  g.season_id,
  g.game_type,
  count(*) as gp,
  sum(t.toi_5v5_sec) as toi_5v5_sec,
  sum(t.cf) as cf, sum(t.ca) as ca,
  sum(t.ff) as ff, sum(t.fa) as fa,
  sum(t.sf) as sf, sum(t.sa) as sa,
  sum(t.gf) as gf, sum(t.ga) as ga
from team_game_onice t
join games g on g.id = t.game_id
group by t.team_id, g.season_id, g.game_type;
