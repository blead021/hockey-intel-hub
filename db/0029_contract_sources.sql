-- 0029: a public source for every contract on file (team announcements and news coverage of the signing).
-- Filled by pipeline.contracts.sourcing; it never changes a contract, it only records what the news says.

create table contract_sources (
  contract_id bigint primary key references contracts (id) on delete cascade,
  status text not null check (status in ('searching', 'confirmed', 'mismatch', 'not_found')),
  found jsonb,                    -- what the announcement states: cap_hit, total_value, years, end_season
  note text,
  source_urls text[],
  searched_at timestamptz,
  checked_at timestamptz
);
