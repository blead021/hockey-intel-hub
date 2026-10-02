-- 0006: team codes are only unique among active teams. Utah Hockey Club (id 59, 2024-25) and
-- Utah Mammoth (id 68, 2025-26 on) both use UTA. 0001's team load wrongly stored Utah as id 59.

alter table teams drop constraint teams_abbrev_key;
create unique index teams_active_abbrev_idx on teams (abbrev) where active;

-- Move Utah Mammoth to its real id (68), keep 59 as the inactive Utah Hockey Club.
update teams set active = false where id = 59;
insert into teams (id, abbrev, name, conference, division, active)
select 68, 'UTA', 'Utah Mammoth', conference, division, true from teams where id = 59
on conflict (id) do nothing;
update teams set name = 'Utah Hockey Club' where id = 59;

update sentiment_feeds set team_id = 68 where team_id = 59;
update mentions set team_id = 68 where team_id = 59;
