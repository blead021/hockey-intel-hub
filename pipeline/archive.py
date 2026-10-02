"""Saves raw API responses to the R2 bucket, so anything can be recomputed later.

Sentiment history cannot be re-collected, so in production (ARCHIVE_REQUIRED=1) a missing
R2 setup stops the job. Locally, archiving is skipped when the R2 keys are not set.
"""

import gzip
import json
import os
import re
import uuid
from datetime import UTC, datetime
from functools import cache

REQUIRED_VARS = ("CLOUDFLARE_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_RAW")


class ArchiveUnavailable(RuntimeError):
    pass


def configured() -> bool:
    return all(os.environ.get(name) for name in REQUIRED_VARS)


def archive_key(source: str, name: str, when: datetime) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")[:80] or "item"
    return f"raw/{source}/{when:%Y/%m/%d}/{safe_name}/{when:%H%M%S}-{uuid.uuid4().hex[:8]}.json.gz"


def save(source: str, name: str, payload) -> str | None:
    """Stores payload under a new timestamped key and returns it, or None when archiving is off locally."""
    return put(archive_key(source, name, datetime.now(UTC)), payload)


def put(key: str, payload) -> str | None:
    """Stores payload at an exact key, replacing any earlier copy. Used for files read back later,
    such as nhl/pbp/{season}/{game_id}.json.gz."""
    if not configured():
        if os.environ.get("ARCHIVE_REQUIRED") == "1":
            missing = [n for n in REQUIRED_VARS if not os.environ.get(n)]
            raise ArchiveUnavailable(f"R2 archive is required but these are not set: {', '.join(missing)}")
        return None
    body = gzip.compress(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
    _s3().put_object(
        Bucket=os.environ["R2_BUCKET_RAW"],
        Key=key,
        Body=body,
        ContentType="application/json",
        ContentEncoding="gzip",
    )
    return key


@cache
def _s3():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['CLOUDFLARE_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(retries={"max_attempts": 5, "mode": "standard"}),
    )
