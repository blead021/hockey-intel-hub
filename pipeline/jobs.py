"""Records each job run, its counts, and any error in the job_runs table."""

import json
import traceback
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager

from pipeline.db import connect


@contextmanager
def job_run(job: str) -> Iterator[Counter]:
    """Use as `with job_run("nhl_nightly") as counts: counts["games_loaded"] += 1`.

    The run is logged on its own connection, so a failed job still leaves a record.
    """
    counts: Counter = Counter()
    with connect(autocommit=True) as log:
        run_id = log.execute("insert into job_runs (job) values (%s) returning id", (job,)).fetchone()[0]
        counts.run_id = run_id  # lets a job link its own records to this run
        try:
            yield counts
        except BaseException:
            log.execute(
                "update job_runs set status = 'failed', finished_at = now(), counts = %s, error = %s where id = %s",
                (json.dumps(counts), traceback.format_exc(limit=20), run_id),
            )
            raise
        log.execute(
            "update job_runs set status = 'success', finished_at = now(), counts = %s where id = %s",
            (json.dumps(counts), run_id),
        )
