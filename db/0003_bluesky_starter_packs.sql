-- 0003: allow Bluesky starter packs as a feed kind (all posts from the pack's members).

alter table sentiment_feeds drop constraint sentiment_feeds_kind_check;
alter table sentiment_feeds add constraint sentiment_feeds_kind_check check (kind in (
  'subreddit', 'bluesky_account', 'bluesky_starter_pack', 'bluesky_search', 'rss', 'google_news', 'youtube_channel'));
