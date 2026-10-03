-- 0049: goalie splits for the Player Profile's goalie metrics: high-danger shots (xG of 0.15 or more) and 5v5.
-- Null for games computed before this migration until the on-ice job reloads them.

alter table goalie_game_xg
  add column hd_shots integer,
  add column hd_goals integer,
  add column hd_xga numeric(7, 3),
  add column shots_5v5 integer,
  add column goals_5v5 integer,
  add column xga_5v5 numeric(7, 3);
