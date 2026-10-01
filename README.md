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

GitHub Actions secrets needed so far: `DATABASE_URL_UNPOOLED`.
