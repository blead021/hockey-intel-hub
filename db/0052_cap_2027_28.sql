-- 0052: the 2027-28 salary cap ceiling, $113.5M, as announced by the NHL and NHLPA (the multi-year cap
-- projection agreed in 2025). Lets the team page show next season's cap space. Minimum salary not set yet.

insert into seasons (id, regular_season_games) values (20272028, 84) on conflict (id) do nothing;

insert into cap_limits (season_id, cap_ceiling) values (20272028, 113500000)
on conflict (season_id) do nothing;
