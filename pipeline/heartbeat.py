"""Scheduled check that GitHub Actions can reach the database and log a job run.

Usage: python -m pipeline.heartbeat
"""

from pipeline.db import connect
from pipeline.jobs import job_run


def main() -> None:
    with job_run("heartbeat") as counts, connect() as conn:
        counts["data_sources_enabled"] = conn.execute(
            "select count(*) from data_sources where enabled"
        ).fetchone()[0]
    print(f"heartbeat ok: {dict(counts)}")


if __name__ == "__main__":
    main()
