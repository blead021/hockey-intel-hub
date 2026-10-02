-- 0014: 5v5 points per game, for IPP (individual points percentage).
-- IPP = 5v5 points / 5v5 on-ice goals for (CLAUDE.md section 6).

alter table game_skater_stats add column points_5v5 smallint not null default 0;
