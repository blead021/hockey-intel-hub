# Puckwise

Product name: **Puckwise** (renamed from Hockey Intel Hub on 2026-10-02). Infrastructure names (GitHub repo, Cloudflare Worker, Neon project, R2 bucket, Hyperdrive config, local folder) intentionally keep the hockey-intel names; only the public name is Puckwise.

A subscription web app that gives hockey fans "front office tools": player stats, advanced analytics, fan and beat-writer sentiment, trade chatter, contracts, and age, organized into connected screens: League, My Team / Team Roster, Player Profile, Trade Targets, Trade Builder, and a Rumor Tracker.

Audience: hockey fans, fantasy players, bettors, and hockey writers. Business model: freemium, with a low-cost paid subscription sold on the web through Stripe.

Owner: Brian Leadbetter. Brian is not a full-time developer. Explain decisions in plain language, keep setup steps explicit, and ask before adding paid services.

## Writing style

- Use commas instead of em dashes in all prose, UI copy, comments, and docs.

---

## 1. Architecture

| Layer | Choice | Notes |
|---|---|---|
| Front end | Next.js (App Router, TypeScript) | Deployed to Cloudflare Workers via the OpenNext Cloudflare adapter |
| Database | Neon Postgres | Reached from Workers through Cloudflare Hyperdrive; Python jobs connect directly |
| Data jobs | Python 3.12 on GitHub Actions cron | NHL ingestion, metrics, xG, sentiment collectors (Reddit, Bluesky, YouTube, RSS), sentiment scoring, team grades |
| Light scheduled jobs (optional, later) | Cloudflare Workers Cron Triggers | Only if a collector needs polling more often than GitHub Actions allows. Decided 2026-10-01 to keep all collectors in Python, since free Workers allow only 10 ms of CPU per run |
| Raw archive | Cloudflare R2 | Store raw JSON from every API pull so metrics can be recomputed |
| Auth | Clerk (or Supabase Auth if simpler) | Public sign-up with email and Google login |
| Payments | Stripe Checkout, Stripe Customer Portal, Stripe Billing webhooks, Stripe Tax | Web only, no app store billing |
| Email | Resend (or Postmark) | Transactional email plus the weekly newsletter |
| AI | Claude API | Sentiment scoring, trade-chatter detection, stat-card image extraction |

Repo layout (monorepo):

```
/web            Next.js app (UI, API routes, auth, billing, gating)
/pipeline       Python package: ingestion, metrics, models, sentiment
  /ingest       one module per source
  /metrics      derived stats, per-60 rates, on-ice metrics
  /models       xG model, surplus value, team grades, aging curves
  /sentiment    collectors, Claude scoring, aggregation
/db             SQL migrations (plain SQL, numbered)
/workers        Cloudflare cron workers (TypeScript)
/emails         newsletter and transactional email templates
/.github/workflows   scheduled pipeline jobs
```

Secrets live in GitHub Actions secrets and Cloudflare secrets, never in the repo. Maintain `.env.example` with every variable name.

---

## 2. Business model and access

### Plans
- Free: League page (needs grid, Top 10 trade targets, Top 10 undervalued), the user's one favorite team (My Team), and the weekly email.
- Paid ("Pro"): every team, all Player Profiles, Trade Targets with filters, Trade Builder, Rumor Tracker, watchlists, and alerts.
- Two paid prices, configured in the Stripe dashboard, never hardcoded: a monthly plan and an annual plan. Brian is choosing final prices; options under consideration are $2/month billed annually ($24/year), $4.99/month, and $29.99/year. Read price IDs from environment variables.
- Low price points lose a large share to per-transaction card fees, so present the annual plan as the default choice on the pricing page.

### Gating rules
- Enforce access on the server (route handlers, server components, and API routes). Never rely on hiding things in the browser.
- One helper, `getAccess(user)`, returns the plan and the list of unlocked features. Every gated page and API route uses it.
- Logged-out visitors see the free pages. Paid pages show a preview (blurred or truncated) with an upgrade prompt.

### Billing flow
1. User signs up (Clerk) and picks a favorite team during onboarding.
2. Upgrade button opens Stripe Checkout for the chosen price.
3. Stripe webhook (`/api/stripe/webhook`, signature verified) updates `users.plan`, `subscription_status`, `stripe_customer_id`, and `current_period_end`.
4. "Manage subscription" opens the Stripe Customer Portal for card changes and cancellation.
5. Handle `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, and `invoice.payment_failed`. Webhook processing must be idempotent.
6. Build and test everything in Stripe test mode first. Turn on Stripe Tax before going live.

### Required pages
Landing page (what it does, screenshots, pricing), Pricing, Sign in / Sign up, Onboarding (pick favorite team), Account (plan, manage billing, email preferences), Terms of Service, Privacy Policy, and a contact page. Brian will supply final legal text; generate clearly marked placeholders.

### Data source switches
Each external data source has an on/off flag in a `data_sources` config table. Before launch Brian will confirm which sources allow commercial use. The app must still work, with that section hidden or marked "unavailable", when any single source is switched off.

---

## 3. Data sources

Treat every source as unreliable: validate, retry with backoff, respect rate limits, cache raw responses to R2, and never scrape a site whose terms forbid it.

### NHL (free, unofficial, undocumented)
Base: `https://api-web.nhle.com/v1/` and `https://api.nhle.com/stats/rest/en/`. Endpoints change without notice, so wrap each in a single client module with schema checks and clear errors. Needed data:
- Schedule by date, team rosters, player landing pages (birth date, position, shoots, height, weight)
- Game boxscores (goals, assists, shots, hits, blocks, TOI, PP TOI, PK TOI, faceoffs, giveaways, takeaways, plus-minus)
- Play-by-play with event coordinates (for Corsi, Fenwick, xG, zone starts)
- Shift charts (who was on the ice for each event)
- NHL EDGE player data (zone time, skating speed, bursts, shot speed). Discover the current EDGE endpoints first and document them in `/pipeline/ingest/README.md`.

### Expected goals
- Phase 3 starts with MoneyPuck's shot-level data for xG values (check its terms, it may be a personal-use-only source).
- Then train our own xG model (see section 6), which removes that dependency.

### Contracts
- Starting data: Brian fills in `contracts_template.xlsx` (repo root) once, with every current contract. `python -m pipeline.ingest.contracts` loads it. Columns: player, team, cap_hit, aav, start_season, end_season, expiry_status (UFA/RFA), clause (NMC, NTC, M-NTC, none), no_trade_list_size, retained_pct, retained_by. Required: player, team, cap_hit, start_season, end_season. Every row with a player and a team is loaded; missing or unreadable details are stored as unknown, and every such row is reported to Brian. Loading again refuses to erase news updates unless `--replace` is given.
- After that, contracts stay current automatically with no manual work from Brian. The daily job `python -m pipeline.contracts.update` (GitHub Actions, `contracts-daily.yml`) reads headlines of official team announcements and news coverage (Google News results, mainly NHL.com), uses Claude (`CONTRACTS_MODEL`, default `claude-opus-5-5`) to extract signings, extensions, trades (including retained salary), buyouts, terminations, waiver claims, and entry-level contracts, and applies them under fixed rules in `pipeline/contracts/apply.py`.
- Never scrape PuckPedia, Spotrac, CapWages, CapFriendly, or any other contract database site. The job also never downloads full articles; it reads headlines and feed summaries only.
- Only completed transactions are applied. Reported deals and rumors are logged and skipped.
- When the news does not mention a detail, keep the value on file. For a new contract, store missing details as unknown (NULL, shown as "unknown"). Never guess, and never ask Brian to fill anything in. The only derived values are arithmetic on stated facts (cap hit = total value / years; one end of a season range from the other end and the length; an extension's first season as the season after the contract in force ends), and the log says when one was used.
- Log every change: `contract_events` (each transaction found, its outcome, and source links) and `contract_changes` (each field changed, old and new values, sources). Brian can see them at `/contracts/changes` on the site or with `python -m pipeline.contracts.changes`.
- Behind the `contract_news` data source switch. The Claude API is a paid service (estimated $3-5 per month at current volume); it needs `ANTHROPIC_API_KEY`.
- Cap ceiling 2026-27: $104,000,000. Store per season in a `cap_limits` table.

### HockeyStatCards
- Brian subscribes to the post-game email cards. Read labeled emails through the Gmail API, extract numbers from the card images with Claude vision, and store them in `hsc_game_scores`.
- Cross-check extracted goals, assists, and TOI against the NHL boxscore. Flag mismatches for review instead of saving silently.
- Behind its own data source switch, since commercial use needs HockeyStatCards' permission. Our computed Game Score is the fallback.

### Sentiment sources
- Reddit: r/hockey plus all 32 team subreddits, especially game threads and post-game threads (official API, OAuth).
- Bluesky: public posts from a curated list of beat writers and insiders, plus keyword search (AT Protocol).
- YouTube: comments on team highlight and press conference videos (YouTube Data API, stay within the free daily quota).
- News: Google News RSS per player, plus RSS feeds from team beat writers and local outlets. Store headline, snippet, URL, and date only. Never store or republish full articles, and never display raw quotes longer than a short phrase; show our one-line summaries with a link to the source.
- Every mention is tagged with an audience: `fan`, `beat_writer`, or `media`.

### Optional paid feeds (ask before adding)
- Evolving-Hockey (WAR/GAR), All Three Zones (zone entries and exits).

---

## 4. Player identity (critical)

Every source names players differently. Build this before any sentiment work.
- `players` uses the NHL player ID as the primary key.
- `player_aliases` maps every alternate name, nickname, and source-specific ID to that key (for example "Q. Hughes", "Quinn", "Huggy").
- Sentiment matching must use context (team, subreddit, teammates mentioned) to separate players who share a surname. Low-confidence matches go to a `needs_review` state, not into the scores.

---

## 5. Database schema (starting point)

Core: `teams`, `seasons`, `cap_limits`, `players`, `player_aliases`, `games`, `data_sources`

Stats:
- `game_skater_stats` (player_id, game_id, team_id, g, a1, a2, sog, hits, blocks, toi_sec, pp_toi_sec, pk_toi_sec, fow, fol, giveaways, takeaways, plus_minus)
- `game_goalie_stats` (player_id, game_id, shots_against, saves, ga, toi_sec)
- Play-by-play and shifts are NOT database tables (decided 2026-10-02 to keep Neon on the free plan). They are stored in R2 as one gzipped JSON file per game, at `nhl/pbp/{season}/{game_id}.json.gz` and `nhl/shifts/{season}/{game_id}.json.gz`. Python jobs read them to compute per-game results (on-ice metrics, xG, zone starts) and save only those results to Postgres.
- `player_game_onice` (5v5 CF, CA, FF, FA, GF, GA, xGF, xGA, HDCF, HDCA, OZ starts, DZ starts)
- `edge_player_stats` (player_id, season, as_of, oz_time_pct, dz_time_pct, top_speed, bursts_20plus, max_shot_speed)
- `hsc_game_scores` (player_id, game_id, game_score, raw_fields jsonb, verified bool)

Money and value: `contracts` (adds status active/bought_out/terminated, contract_type, source starting_file/news; unknown details are NULL), `contract_news` (headlines read), `contract_events` (transactions found and their outcome), `contract_changes` (every field changed, with sources), `player_value` (player_id, as_of, war_proj, market_aav_est, surplus)

Sentiment: `mentions` (id, source, audience, url, author, posted_at, text, raw jsonb), `mention_players` (mention_id, player_id, confidence, sentiment -1..1, is_trade_related, summary), `sentiment_daily` (player_id, date, audience, score_0_100, n_mentions, trade_mentions)

League: `team_grades` (team_id, as_of, category, value, z, grade -2..2), `aging_curves` (position, age, index)

Users and billing:
- `users` (id, auth_provider_id, email, favorite_team_id, plan free/pro, subscription_status, stripe_customer_id, stripe_subscription_id, price_interval monthly/annual, current_period_end, created_at)
- `stripe_events` (event_id, type, processed_at) for idempotent webhook handling
- `email_subscribers` (email, user_id nullable, weekly_digest bool, unsubscribed_at)
- `watchlists`, `trade_scenarios`, `alerts`, `job_runs`

Season-level views aggregate game tables. Write each migration as plain SQL in `/db`.

---

## 6. Metric definitions

All on-ice metrics are 5v5 unless stated. Per-60 = stat / TOI minutes x 60.

- Points = G + A1 + A2. Primary points = G + A1.
- Faceoff % = FOW / (FOW + FOL). Show only for players with 50+ draws. Shown on Player Profile and Team Roster only.
- Corsi (CF, CA): shot attempts (goals, shots on goal, missed, blocked) while on ice. CF% = CF / (CF + CA).
- Fenwick: Corsi excluding blocked shots.
- Relative CF% and xGF%: player's on-ice % minus his team's % while he is off the ice.
- xGF% = xGF / (xGF + xGA).
- High-danger chances: shots with xG >= 0.15 (tune, document the threshold).
- PDO = on-ice shooting % + on-ice save %, scaled so 100 is average.
- IPP = player points / team goals scored while he is on ice.
- OZS% = offensive zone faceoff starts / (offensive + defensive zone starts).
- ixG = sum of xG on the player's own shots. Goals above expected = G - ixG.
- GSAx (goalies) = xG against - goals against.
- Game Score (Luszczyszyn, verify coefficients before shipping): 0.75 G + 0.7 A1 + 0.55 A2 + 0.075 SOG + 0.05 BLK + 0.15 PD - 0.15 PT + 0.01 FOW - 0.01 FOL + 0.05 CF - 0.05 CA + 0.15 GF - 0.15 GA. Prefer HockeyStatCards' value when that source is enabled.
- Cap % = cap hit / cap ceiling for that season.
- Age = computed from birth date as of today. Aging index from historical production by position and age.

### xG model
Gradient-boosted classifier on unblocked shots. Features: distance, angle, shot type, rebound (shot within 3 seconds of a prior shot), rush (shot within 4 seconds of an event in another zone), strength state, empty net, score state, prior event type. Train on at least three past seasons, validate on a held-out season, report log loss and calibration, and compare against MoneyPuck before switching.

### WAR
If Evolving-Hockey is not licensed, build a simplified regularized model from on-ice xG impact, individual scoring, and penalties. Label it clearly as our estimate.

### Surplus value
Estimate market AAV with a comparables model (nearest neighbors on age, position, WAR/82, points/82 over the prior three seasons, adjusted to cap %). Surplus = market AAV estimate - cap hit.

### Sentiment
- Claude scores each mention: target players, sentiment -1 to 1, is_trade_related, one-line summary. Batch requests, use a small fast model (for example `claude-haiku-4-5-20251001`), and cache by mention ID so nothing is scored twice.
- Daily score per player per audience = 50 + 50 x (recency-weighted mean sentiment). Require a minimum mention count before displaying a score.
- Trend = score change over 14 days.
- Trade chatter = trade-related mentions in the last 7 days. Spike = 7-day count at least 2x the prior 4-week weekly average.
- Perception gap = performance percentile (blend of xGF%, WAR, Game Score by position) - fan sentiment score.

### Team need grades
Categories: goal scoring, playmaking, physicality, 5v5 defense, power play, penalty kill, goaltending, prospect depth. Compute each team's metric, z-score across 32 teams, map to grades -2 (Need), -1 (Thin), 0 (Average), 1 (Solid), 2 (Surplus). Document the metric used for each category.

### Best fits
Teams graded Need or Thin in the player's strength category, with cap space >= cap hit x 0.5 (the 50% retention limit), excluding his current team, sorted by need severity then cap space.

---

## 7. Screens

The approved mockups are the design source of truth for the five core screens. Match their layout and content.

1. League (free): 32-team needs grid with cap space, summary cards, Top 10 trade targets with best fits, Top 10 undervalued by perception gap. Conference filter.
2. Team Roster (free for the user's favorite team as "My Team", paid for all others): team selector, summary cards (cap committed, space, roster count, 5v5 xGF%, PP/PK, fan sentiment), forwards and defense table (GP, G, A, P, TOI, FO% for centers, xGF%, WAR, cap hit, years, expiry, clause, fan sentiment, chatter), goalie table (SV%, GAA, GSAx), cap by position, expiring contracts, most trade chatter.
3. Player Profile (paid; free for players on My Team): header with contract, clause, surplus value; stat cards including Faceoff %; last-5 game log including FO won-lost; advanced metrics with percentile bars; sentiment by audience with 14-day chatter chart, signals, latest mentions; age curve; NHL EDGE skating.
4. Trade Targets (paid): filterable list (position, age, cap hit, term, clauses, chatter, buy-low), cap fit vs. a chosen team with required retention, WAR, surplus, sentiment, chatter, signal tags, alert cards. No FO% here.
5. Trade Builder (paid): two-sided deal, cap impact for both teams, retention slider (max 50%), automatic checks (cap compliance, no-trade list, retention slots, roster count, term vs. age curve), comparable trades, market read. Users can save and share scenarios.
6. Rumor Tracker (paid, new): league-wide feed of trade-related mentions grouped by player, with chatter volume, 14-day trend, sentiment by audience, and whether chatter is rising or fading. Filter by team and position. Show our summaries and source links, not copied text.
7. Business pages from section 2: landing, pricing, onboarding, account, legal, contact.

Navigation: My Team is the default landing page for signed-in users.

Design tokens: background #F4F3EF, surface #FFFFFF, ink #16181D, muted text #4F5561, borders #DCDAD3 and #ECEAE4, positive blue #1D5AA6 (soft #E4ECF7), negative orange #B4501A (soft #FBEBDD). Fonts: Barlow Condensed (headings), IBM Plex Sans (body), IBM Plex Mono (numbers). Positive vs. negative must differ in lightness, not only color. Pages must work well on phones, since many fans will browse on mobile.

---

## 8. Build phases

Finish and verify each phase before starting the next. At the end of each phase, summarize what works, what is stubbed, and any data issues.

### Phase 0: Setup
Monorepo scaffold, Neon database, migrations runner, Next.js on Cloudflare (OpenNext), Hyperdrive, R2 bucket, GitHub Actions skeleton, `data_sources` config table, `.env.example`, README with setup steps.

### Phase 1: Sentiment collectors first
The season is starting and sentiment history cannot be backfilled, so start collecting now: Reddit, Bluesky, YouTube, and RSS collectors writing raw mentions to `mentions` and R2 on a schedule. Scoring comes later.

### Phase 2: Core stats and rosters
Players, aliases, rosters, games, boxscores, play-by-play, shifts, EDGE. Nightly job plus a backfill command for the current and past three seasons. Contracts: one-time import of `contracts_template.xlsx`, then the automated daily contract news job. Team Roster and Player Profile pages on real data (no login yet).
Done when: any team's roster page and any player's profile render real numbers that match NHL.com for spot-checked games.

### Phase 3: Advanced metrics
On-ice metrics, per-60 rates, zone starts, relative stats, MoneyPuck xG, Game Score, HockeyStatCards email ingestion with cross-checks. Then our own xG model.

### Phase 4: Sentiment scoring
Player matching, Claude scoring, daily aggregation, trade chatter, spikes, perception gap. Sentiment panels live on Profile and Roster. Rumor Tracker page.

### Phase 5: League and trade tools
Team grades, League page, Trade Targets filters and signals, Trade Builder with cap math and checks, surplus value, aging curves, best fits.

### Phase 6: Accounts, billing, and launch
Clerk sign-up and onboarding (favorite team), My Team landing, `getAccess` gating on every paid page and API route, Stripe Checkout (monthly and annual), webhooks, Customer Portal, Stripe Tax, pricing and landing pages, account page, legal placeholders, watchlists, saved scenarios, alerts, weekly email with unsubscribe, job failure notifications, error monitoring.
Done when: in Stripe test mode, a new user can sign up, pick a team, subscribe, see paid pages unlock, cancel in the portal, and lose access at period end.

### Phase 7: Growth (after launch)
Free weekly newsletter (top undervalued players, chatter spikes), shareable chart images for Bluesky and X, public "undervalued of the week" page for search traffic, referral or free-trial options.

---

## 9. Working rules

- Tests for every metric function, using small hand-checked fixtures (for example a single game where CF% can be calculated by hand).
- Tests for gating: free users cannot reach paid data through the UI or the API.
- Every ingestion job is idempotent: rerunning a date never duplicates rows.
- Log counts per job run (games loaded, mentions collected, mismatches flagged) to `job_runs`.
- Keep monthly spend visible: note any new paid service or API cost before adding it.
- Prefer boring, well-documented libraries. Explain any new dependency in one line.
