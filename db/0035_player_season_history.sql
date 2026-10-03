-- 0035: 25 seasons of NHL season totals (from 2001-02), for age curves. Season level only: small enough for
-- the free database. Not linked to players: most of these players have retired.

create table player_season_history (
  player_id integer not null,              -- NHL player id
  season_id integer not null,
  grp text not null check (grp in ('F', 'D', 'G')),
  name text not null,
  birth_date date,
  gp smallint not null,
  toi_sec integer,                         -- skaters: total ice time
  goals smallint,
  points smallint,
  shots smallint,
  shots_against integer,                   -- goalies
  saves integer,
  goals_against smallint,
  primary key (player_id, season_id)
);
