# Hockey Intel Hub

Front office tools for hockey fans: player stats, advanced analytics, fan and beat-writer sentiment,
trade chatter, and contracts. See `CLAUDE.md` for the full product and build plan.

## What is where

| Folder | What it holds |
|---|---|
| `web/` | Next.js app (pages, API routes), deployed to Cloudflare Workers with OpenNext |
| `pipeline/` | Python jobs: ingestion, metrics, models, sentiment |
| `db/` | Numbered SQL migrations (`0001_core.sql`, `0002_...`) |
| `workers/` | Small Cloudflare cron workers (from Phase 1) |
| `emails/` | Email templates (from Phase 6) |
| `.github/workflows/` | CI checks, database migrations, scheduled pipeline jobs |

## Accounts and services

| Service | Used for | Cost today |
|---|---|---|
| Neon | Postgres database (project `hockey-intel-hub`) | Free plan |
| Cloudflare | Hosting (Workers), Hyperdrive, R2 raw archive | Free plan limits; Workers Paid ($5/month) only if we outgrow them |
| GitHub | Code, CI, scheduled jobs | Free for normal use |

## First-time setup on a new computer

You need Node.js 24 or newer, Python 3.12 or newer, and git.

1. **Secrets file.** Copy `.env.example` to `.env` at the repo root and fill in the database values.
   Get the connection strings with:
   ```
   npx neonctl connection-string --project-id <NEON_PROJECT_ID> --pooled   # DATABASE_URL
   npx neonctl connection-string --project-id <NEON_PROJECT_ID>            # DATABASE_URL_UNPOOLED
   ```
   Set `CLOUDFLARE_HYPERDRIVE_LOCAL_CONNECTION_STRING_HYPERDRIVE` to the same value as `DATABASE_URL_UNPOOLED`.

2. **Python pipeline.**
   ```
   python -m venv .venv
   .venv\Scripts\activate          (Windows)   or   source .venv/bin/activate   (Mac/Linux)
   pip install -e ".[dev]"
   pytest
   ```

3. **Database tables.**
   ```
   python -m pipeline.migrate            apply any new migrations
   python -m pipeline.migrate --status   see which migrations are applied
   ```

4. **Web app.**
   ```
   cd web
   npm install
   npm run dev
   ```
   Open http://localhost:3000. The page links to `/api/health`, which should say `"database": "connected"`.

## Everyday commands

| Task | Command |
|---|---|
| Run the web app locally | `cd web` then `npm run dev` |
| Run it in Cloudflare's runtime locally | `cd web` then `npm run preview` |
| Deploy the web app | `cd web` then `npm run deploy` |
| Run Python tests | `pytest` |
| Apply database migrations | `python -m pipeline.migrate` |
| Check the scheduled-job path | `python -m pipeline.heartbeat` |

## Changing the database

Never edit a migration that has already been applied. Add a new file with the next number,
for example `db/0002_mentions.sql`. The runner refuses to continue if an applied file changes.
On GitHub, pushing a change under `db/` to `main` applies it automatically.

## Sentiment collection

Collectors for news, Bluesky, Reddit, and YouTube run every 3 hours on GitHub Actions
(`.github/workflows/collect-sentiment.yml`). Each run saves the full raw response to R2, then adds
new items to the `mentions` table. Scoring comes later (Phase 4).

| Task | Command |
|---|---|
| Collect everything now | `python -m pipeline.sentiment.collect` |
| Collect one source | `python -m pipeline.sentiment.collect --source news_rss` (or `bluesky`, `reddit`, `youtube`) |
| Load an edited feed list | `python -m pipeline.sentiment.feeds` |
| Refresh the 32 teams | `python -m pipeline.ingest.nhl_teams` |

**What gets watched** is in `pipeline/sentiment/feeds.csv`. Open it in Excel, add or remove rows,
save as CSV, and push. Each run loads the file first. Columns:

| Column | Meaning |
|---|---|
| kind | `subreddit`, `bluesky_account`, `bluesky_starter_pack`, `bluesky_search`, `rss`, `google_news`, or `youtube_channel` |
| value | Subreddit name, Bluesky handle, starter pack link, search words, feed URL, or YouTube handle (like `@canucks`) |
| team | Team code like `VAN`, or blank for league-wide |
| audience | `fan`, `beat_writer`, or `media` |
| label, notes | For people; not used by the code |
| active | `yes` or `no` |

A collector without its keys skips itself and says so in `job_runs`. A feed that keeps failing
shows its error in `collector_state.last_error`.

## Data source switches

Every external source has a row in the `data_sources` table. To switch one off:

```sql
update data_sources set enabled = false, updated_at = now() where key = 'reddit';
```

Jobs check the switch before running, and the app hides or marks that section unavailable.
Before launch, set `commercial_use_confirmed = true` only for sources whose terms allow it.

## Secrets

Secrets live in `.env` locally, in GitHub Actions secrets for scheduled jobs, and in Cloudflare
secrets for the web app. `.env.example` lists every name. Never commit real values.

GitHub Actions secrets: `DATABASE_URL_UNPOOLED`, `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
`R2_SECRET_ACCESS_KEY`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`,
`BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD`, `YOUTUBE_API_KEY`.
