# Cloudflare cron workers

Light scheduled jobs that only need to insert rows, such as RSS and Bluesky polling.
Each worker gets its own folder with a `wrangler.jsonc` and connects to Neon through Hyperdrive.

The first workers are built in Phase 1 (sentiment collectors).
