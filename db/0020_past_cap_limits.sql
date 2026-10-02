-- 0020: official NHL salary cap ceilings and floors for past seasons, so older roster pages show cap space.
-- 2026-27 floor is added once confirmed.

insert into cap_limits (season_id, cap_ceiling, cap_floor) values
  (20222023, 82500000, 61000000),
  (20232024, 83500000, 61700000),
  (20242025, 88000000, 65000000),
  (20252026, 95500000, 70600000)
on conflict (season_id) do nothing;
