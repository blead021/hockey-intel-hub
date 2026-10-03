-- 0034: official cap ceilings for 2018-19 to 2021-22, so contracts signed then are measured against their own cap.
insert into seasons (id, regular_season_games) values
  (20182019, 82), (20192020, 82), (20202021, 56), (20212022, 82)
on conflict (id) do nothing;

insert into cap_limits (season_id, cap_ceiling) values
  (20182019, 79500000), (20192020, 81500000), (20202021, 81500000), (20212022, 81500000)
on conflict (season_id) do nothing;
