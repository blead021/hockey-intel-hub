-- 0004: switch Reddit off. As of 2026-10, Reddit only approves new Data API apps for moderation
-- use cases; commercial use needs a paid data license. The collector code stays in place.

update data_sources
set enabled = false,
    notes = 'Off since 2026-10-02: Reddit approves new API apps only for moderation tools. '
         || 'Commercial use needs a Reddit data license. Turn on only after a license is in place.',
    updated_at = now()
where key = 'reddit';
