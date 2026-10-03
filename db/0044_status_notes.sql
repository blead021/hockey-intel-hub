-- 0044: where a player status came from, so manual corrections (moves the news never reported) are visible.
alter table player_status add column source text not null default 'news';   -- news, roster, manual
alter table player_status add column note text;
