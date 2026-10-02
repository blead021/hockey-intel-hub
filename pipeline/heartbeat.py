"""Daily health check: database reachable, size, and how much each source collected yesterday.

Usage: python -m pipeline.heartbeat

The Neon free plan holds 0.5 GB, so database size is logged daily to catch growth early.
"""

from pipeline.db import connect
from pipeline.jobs import job_run


def main() -> None:
    with job_run("heartbeat") as counts, connect() as conn:
        counts["data_sources_enabled"] = conn.execute(
            "select count(*) from data_sources where enabled"
        ).fetchone()[0]
        counts["db_mb"] = conn.execute("select pg_database_size(current_database()) / 1048576").fetchone()[0]
        for source, n in conn.execute(
            "select source, count(*) from mentions where collected_at > now() - interval '1 day' group by source"
        ):
            counts[f"mentions_24h_{source}"] = n
        counts["feeds_failing"] = conn.execute(
            "select count(*) from collector_state where consecutive_failures >= 3"
        ).fetchone()[0]
    print(f"heartbeat ok: {dict(counts)}")


if __name__ == "__main__":
    main()
