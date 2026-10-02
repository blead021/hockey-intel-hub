-- 0016: Claude sentiment scoring runs as Message Batches (half price, results within hours).
-- Each batch is tracked so mentions are never sent twice and results are applied once.

create table sentiment_batches (
  id text primary key,                  -- the Anthropic batch id
  model text not null,
  status text not null default 'submitted' check (status in ('submitted', 'applied', 'failed')),
  mention_ids bigint[] not null,
  groups jsonb not null,                -- request custom_id -> mention ids in that request, in order
  requests integer not null,
  submitted_at timestamptz not null default now(),
  applied_at timestamptz,
  input_tokens bigint,
  output_tokens bigint,
  note text
);

-- Off until Brian approves the cost of scoring (Claude API, paid).
insert into data_sources (key, name, enabled, notes) values
  ('sentiment_scoring', 'Sentiment scoring with Claude (claude-haiku-4-5, Message Batches)', false,
   'Paid. Turn on after Brian approves the monthly cost and ANTHROPIC_API_KEY is set.')
on conflict (key) do nothing;
