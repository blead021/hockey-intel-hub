"""Scores shots with the active expected goals model (the one marked active in xg_models).

Raw values are stored. Pages and reports apply the season adjustment (league goals / league xG for
that season, see db/0011) so that each season's total xG equals its goals.
"""

import io
import os
from functools import cache

import numpy as np

from pipeline import archive
from pipeline.models.xg_features import ShotRow
from pipeline.models.xg_train import matrix

HIGH_DANGER = 0.15  # CLAUDE.md section 6: shots with xG >= 0.15


class NoActiveModel(RuntimeError):
    pass


@cache
def active_model(version: str, r2_key: str):
    import joblib

    if not archive.configured():
        raise archive.ArchiveUnavailable("R2 credentials are needed to load the xG model")
    body = archive._s3().get_object(Bucket=os.environ["R2_BUCKET_RAW"], Key=r2_key)["Body"].read()
    return joblib.load(io.BytesIO(body))["model"]


def load(conn):
    """Returns (version, model) for the active model, or raises NoActiveModel."""
    row = conn.execute("select version, r2_key from xg_models where active").fetchone()
    if not row:
        raise NoActiveModel("No active xG model. Train one with: python -m pipeline.models.xg_train --activate")
    return row[0], active_model(row[0], row[1])


def score(model, rows: list[ShotRow]) -> dict[int, float]:
    """xG per event id."""
    if not rows:
        return {}
    probs = model.predict_proba(matrix([r.features for r in rows]))[:, 1]
    return {r.event_id: float(p) for r, p in zip(rows, probs)}
