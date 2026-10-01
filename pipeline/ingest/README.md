# Ingestion

One module per source. Each module:

- checks its `data_sources` switch before running,
- validates responses and fails with a clear error when an endpoint changes,
- retries with backoff and respects rate limits,
- archives raw responses to R2,
- is idempotent, so rerunning a date never duplicates rows,
- logs its counts through `pipeline.jobs.job_run`.

## NHL endpoints

To be documented in Phase 2, including the current NHL EDGE endpoints.
