-- 0023: team need grades (CLAUDE.md section 6) and a steadier xG season factor early in a season.

-- The season factor (league goals / league xG) was 1.12 after the first 109 goals of 2026-27, which
-- inflated early GSAx and goals above expected. Adding 1,000 goals' worth of "as expected" to both sides
-- keeps it near 1.0 until a season has real volume; a full season (about 8,000 goals) moves by under 0.3%.
create or replace view xg_season_factor as
select g.season_id,
       sum(s.goals) as goals,
       sum(s.ixg) as xg,
       (sum(s.goals) + 1000)::numeric / (sum(s.ixg) + 1000) as factor
from player_game_shooting s
join games g on g.id = s.game_id
where g.game_type = 2
group by g.season_id;

create table team_grades (
  team_id smallint not null references teams (id),
  as_of date not null,
  category text not null,
  value numeric(10, 4),            -- the category's metric (see CLAUDE.md for each)
  z numeric(6, 3),                 -- standard score across the 32 teams, higher is better
  grade smallint check (grade between -2 and 2),  -- -2 Need, -1 Thin, 0 Average, 1 Solid, 2 Surplus
  sample text not null,            -- the seasons and games the grade is built from
  primary key (team_id, as_of, category)
);
