-- 0031: contracts whose signing and length are confirmed by an announcement that gave no dollar figure.
alter table contract_sources drop constraint contract_sources_status_check;
alter table contract_sources add constraint contract_sources_status_check
  check (status in ('searching', 'confirmed', 'term_confirmed', 'mismatch', 'not_found'));
