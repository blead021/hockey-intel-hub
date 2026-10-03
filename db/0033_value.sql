-- 0033: age curves, WAR projections, market value, and surplus value (CLAUDE.md section 6), from
-- pipeline/models/value.py.

create table aging_curves (
  grp text not null check (grp in ('F', 'D', 'G')),
  age smallint not null,
  delta numeric(8, 4),          -- average change in WAR per 82 games from this age to the next (smoothed)
  index numeric(7, 2),          -- production index, 100 at the group's peak age
  pairs integer not null,       -- player season pairs behind it
  primary key (grp, age)
);

create table player_value (
  player_id integer not null references players (id),
  as_of date not null,
  war_proj numeric(7, 3),       -- projected WAR per 82 games next
  market_aav_est numeric(12, 0),-- what comparable veterans are paid, as this season's cap share
  surplus numeric(12, 0),       -- market estimate minus cap hit
  comps integer[],              -- the comparable players used
  primary key (player_id, as_of)
);
