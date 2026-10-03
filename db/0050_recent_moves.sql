-- 0050: players traded, signed, extended, or claimed off waivers in the last 120 days (Brian, 2026-10-03: a team
-- does not move a player it just acquired or just signed), from transactions the contracts job confirmed.
-- The date is the earliest headline about the move. Trade target lists leave these players out.

create view player_recent_moves as
with moves as (
  select e.player_id, e.event_type, coalesce(n.d, e.created_at::date) as moved_on
  from contract_events e
  left join lateral (select min(published_at)::date as d from contract_news where id = any (e.news_ids)) n on true
  where e.player_id is not null and e.event_status = 'completed'
    and e.event_type in ('trade', 'signing', 'extension', 'waiver_claim')
    and e.outcome in ('applied', 'no_change', 'skipped_on_file'))
select distinct on (player_id) player_id, event_type as kind, moved_on
from moves
where moved_on >= current_date - 120
order by player_id, moved_on desc;
