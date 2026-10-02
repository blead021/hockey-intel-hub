# Ingestion

One module per source. Each module:

- checks its `data_sources` switch before running,
- validates responses and fails with a clear error when an endpoint changes,
- retries with backoff and respects rate limits,
- archives raw responses to R2,
- is idempotent, so rerunning a date never duplicates rows,
- logs its counts through `pipeline.jobs.job_run`.

## Commands

| Task | Command |
|---|---|
| Nightly load (new games, last 3 days again, rosters, bios) | `python -m pipeline.ingest.nightly` |
| Load a whole season | `python -m pipeline.ingest.nightly --season 20232024` |
| Reload a season already loaded | `python -m pipeline.ingest.nightly --season 20232024 --reload` |
| NHL EDGE, season to date (weekly) | `python -m pipeline.ingest.nhl_edge` |
| Teams | `python -m pipeline.ingest.nhl_teams` |
| Contracts from `data/contracts.csv` | `python -m pipeline.ingest.contracts` |
| Compare a season with NHL.com | `python -m pipeline.checks.compare_nhl --season 20232024` |

## NHL endpoints

Unofficial and undocumented. All calls go through `pipeline/ingest/nhl.py`. Checked 2026-10-02.

### api-web.nhle.com/v1

| Endpoint | Used for | Notes |
|---|---|---|
| `standings/now` | Current 32 teams, conference, division | No team ids; joined to the stats team list on code and full name |
| `club-schedule-season/{TEAM}/{season}` | Every game of a season | Called for all 32 teams and merged. `gameType` 1 preseason, 2 regular, 3 playoffs |
| `gamecenter/{game_id}/boxscore` | Skater and goalie lines | No A1/A2 split, no faceoff counts, no PP/PK ice time. Goalie splits are strings like `"22/24"` (saves/shots). Backups have `toi` `"00:00"`. Overtime losses are `decision: "O"`. The NHL corrects boxscores for a few days after a game (for example `starter` flags), so the nightly job reloads recent games |
| `gamecenter/{game_id}/play-by-play` | A1/A2, faceoff wins and losses, full player names (`rosterSpots`), event coordinates | Shootout goals have `periodDescriptor.periodType` `"SO"`. Goalies can score; count them separately |
| `roster/{TEAM}/current` | Current rosters with birth date, height, weight | Groups: `forwards`, `defensemen`, `goalies` |
| `player/{id}/landing` | Bio for players not on a current roster | |
| `edge/skater-detail/{id}/{season}/{gameType}` | Top speed, bursts over 20 mph, hardest shot, distance skated, zone time, with league percentiles | 404 when a player has no EDGE data yet. No 22+ mph burst count. Other EDGE endpoints, not used yet: `edge/skater-skating-speed-detail/...`, `edge/skater-zone-time/...` (also has zone starts), `edge/skater-shot-speed-detail/...`, `edge/skater-landing/{season}/{gameType}` |

### api.nhle.com/stats/rest/en

| Endpoint | Used for | Notes |
|---|---|---|
| `team` | Team ids | Several teams share a code over time: Utah Hockey Club (59) and Utah Mammoth (68) are both UTA |
| `shiftcharts?cayenneExp=gameId={id}` | Shifts | About 840 rows per game |
| `skater/timeonice?isAggregate=false&isGame=true&limit=-1&cayenneExp=...` | EV, PP, and PK ice time per player per game | `limit=-1` returns every row. Published a while after each game |
| `skater/summary`, `skater/faceoffwins`, `skater/timeonice`, `goalie/summary` with `isAggregate=true` | Season totals for the NHL.com comparison | |

## Where raw files go (R2)

| Key | Contents |
|---|---|
| `nhl/boxscore/{season}/{game_id}.json.gz` | Boxscore |
| `nhl/pbp/{season}/{game_id}.json.gz` | Play-by-play |
| `nhl/shifts/{season}/{game_id}.json.gz` | Shift chart |
| `nhl/edge/{season}/{date}/{player_id}.json.gz` | EDGE snapshot |
| `raw/{source}/{yyyy}/{mm}/{dd}/...` | Timestamped copies (sentiment collectors, standings) |
