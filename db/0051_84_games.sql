-- 0051: the regular season is 84 games from 2026-27 (new CBA); seasons added later default to 84.

update seasons set regular_season_games = 84 where id >= 20262027;
alter table seasons alter column regular_season_games set default 84;
