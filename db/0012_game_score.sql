-- 0012: penalties drawn and taken per game, and Game Score (Dom Luszczyszyn, 2016).
--
-- Skater Game Score = 0.75 G + 0.7 A1 + 0.55 A2 + 0.075 SOG + 0.05 BLK + 0.15 PD - 0.15 PT
--                     + 0.01 FOW - 0.01 FOL + 0.05 CF - 0.05 CA + 0.15 GF - 0.15 GA
-- Goalie Game Score = -0.75 GA + 0.1 SV
-- PD and PT are penalties drawn and taken (minors, majors, match penalties, and penalty shots;
-- misconducts do not put a team shorthanded and are left out). CF, CA, GF, GA are 5v5 on-ice,
-- so games without NHL shift charts score those terms as zero.
-- When the HockeyStatCards source is switched on, its Game Score is preferred (CLAUDE.md).

alter table game_skater_stats add column penalties_drawn smallint not null default 0;
alter table game_skater_stats add column penalties_taken smallint not null default 0;

create view skater_game_score as
select s.player_id, s.game_id, s.team_id,
       round((0.75 * s.g + 0.7 * s.a1 + 0.55 * s.a2 + 0.075 * s.sog + 0.05 * s.blocks
              + 0.15 * s.penalties_drawn - 0.15 * s.penalties_taken + 0.01 * s.fow - 0.01 * s.fol
              + 0.05 * coalesce(o.cf, 0) - 0.05 * coalesce(o.ca, 0)
              + 0.15 * coalesce(o.gf, 0) - 0.15 * coalesce(o.ga, 0))::numeric, 3) as game_score
from game_skater_stats s
left join player_game_onice o on o.player_id = s.player_id and o.game_id = s.game_id;

create view goalie_game_score as
select player_id, game_id, team_id, round((-0.75 * ga + 0.1 * saves)::numeric, 3) as game_score
from game_goalie_stats;
