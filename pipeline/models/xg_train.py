"""Trains the expected goals (xG) model and checks it on a season it has not seen.

Usage:
    python -m pipeline.models.xg_train                                  train on 2022-23 to 2024-25, test on 2025-26
    python -m pipeline.models.xg_train --train 20222023 20232024 20242025 --test 20252026
    python -m pipeline.models.xg_train --activate                       also make it the model used everywhere

A gradient-boosted classifier on unblocked shots (CLAUDE.md section 6). The report gives log loss,
AUC, Brier score, calibration by bin, and total expected vs actual goals, next to a distance-and-angle
baseline. The model file goes to R2 and its scores to the xg_models table.
"""

import argparse
import gzip
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np

from pipeline import archive
from pipeline.config import REPO_ROOT
from pipeline.db import connect
from pipeline.models.xg_features import CATEGORICAL, COLUMNS, NUMERIC, PRIOR_EVENTS, SHOT_TYPES, shot_rows

CACHE_DIR = REPO_ROOT / ".cache" / "xg"
WORKERS = 8
CATEGORIES = {"shot_type": SHOT_TYPES, "prior_event": PRIOR_EVENTS}


def season_rows(conn, season: int) -> list[dict]:
    """Every unblocked shot of a season (regular season and playoffs), cached on disk after the first read."""
    path = CACHE_DIR / f"{season}.json.gz"
    if path.exists():
        return json.loads(gzip.decompress(path.read_bytes()))
    games = [r[0] for r in conn.execute(
        "select id from games where season_id = %s and stats_loaded_at is not null order by id", (season,))]

    def one(game_id):
        return [
            {"game_id": r.game_id, "event_id": r.event_id, "is_goal": r.is_goal, **r.features}
            for r in shot_rows(archive.get(f"nhl/pbp/{season}/{game_id}.json.gz"))
        ]

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        rows = [row for game in pool.map(one, games) for row in game]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(rows).encode()))
    return rows


def matrix(rows: list[dict]) -> np.ndarray:
    """Feature matrix in COLUMNS order; categories become their index in a fixed list."""
    out = np.empty((len(rows), len(COLUMNS)), dtype=np.float64)
    for i, r in enumerate(rows):
        for j, col in enumerate(NUMERIC):
            out[i, j] = r[col]
        for k, col in enumerate(CATEGORICAL):
            values = CATEGORIES[col]
            out[i, len(NUMERIC) + k] = values.index(r[col]) if r[col] in values else len(values) - 1
    return out


def new_model():
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(
        categorical_features=[COLUMNS.index(c) for c in CATEGORICAL],
        learning_rate=0.05,
        max_iter=600,
        max_leaf_nodes=31,
        min_samples_leaf=100,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=30,
        random_state=0,
    )


def calibration(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    """Shots split into bins of equal size by predicted xG: average predicted vs actual goal rate."""
    order = np.argsort(p)
    out = []
    for chunk in np.array_split(order, bins):
        out.append({"shots": int(len(chunk)), "predicted": round(float(p[chunk].mean()), 4),
                    "actual": round(float(y[chunk].mean()), 4)})
    return out


def evaluate(y: np.ndarray, p: np.ndarray) -> dict:
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    return {
        "log_loss": float(log_loss(y, p)),
        "auc": float(roc_auc_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "goals": int(y.sum()),
        "expected_goals": float(p.sum()),
        "calibration": calibration(y, p),
    }


def main(argv: list[str] | None = None) -> None:
    import joblib
    from sklearn.linear_model import LogisticRegression

    parser = argparse.ArgumentParser(description="Train and test the xG model")
    parser.add_argument("--train", type=int, nargs="+", default=[20222023, 20232024, 20242025])
    parser.add_argument("--test", type=int, default=20252026)
    parser.add_argument("--activate", action="store_true", help="make this the model used for all xG")
    args = parser.parse_args(argv)
    if args.test in args.train:
        raise SystemExit("The test season must not be one of the training seasons.")

    with connect() as conn:
        train_rows = [r for s in args.train for r in season_rows(conn, s)]
        test_rows = season_rows(conn, args.test)
        X_train, y_train = matrix(train_rows), np.array([r["is_goal"] for r in train_rows])
        X_test, y_test = matrix(test_rows), np.array([r["is_goal"] for r in test_rows])
        print(f"training shots {len(y_train):,} ({y_train.sum():,} goals); test shots {len(y_test):,} ({y_test.sum():,} goals)")

        model = new_model().fit(X_train, y_train)
        p_test = model.predict_proba(X_test)[:, 1]
        result = evaluate(y_test, p_test)

        geo = [COLUMNS.index("distance"), COLUMNS.index("angle")]
        baseline = LogisticRegression(max_iter=1000).fit(X_train[:, geo], y_train)
        result["baseline_log_loss"] = float(evaluate(y_test, baseline.predict_proba(X_test[:, geo])[:, 1])["log_loss"])
        result["train_log_loss"] = float(evaluate(y_train, model.predict_proba(X_train)[:, 1])["log_loss"])

        print(json.dumps({k: v for k, v in result.items() if k != "calibration"}, indent=2))
        print("calibration (predicted vs actual goal rate, 10 equal bins):")
        for b in result["calibration"]:
            print(f"  {b['predicted']:.3f}  {b['actual']:.3f}")

        version = f"xg-{date.today().isoformat()}"
        buffer = io.BytesIO()
        joblib.dump({"model": model, "columns": COLUMNS, "categories": CATEGORIES, "version": version}, buffer)
        key = f"models/xg/{version}/model.joblib"
        _put_bytes(key, buffer.getvalue())
        archive.put(f"models/xg/{version}/report.json", {**result, "train_seasons": args.train, "test_season": args.test})

        with conn.transaction():
            if args.activate:
                conn.execute("update xg_models set active = false where active")
            conn.execute(
                """insert into xg_models (version, train_seasons, test_season, train_shots, test_shots, log_loss,
                       baseline_log_loss, auc, brier, goals, expected_goals, calibration, r2_key, active)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   on conflict (version) do update set trained_at = now(), train_seasons = excluded.train_seasons,
                     test_season = excluded.test_season, train_shots = excluded.train_shots,
                     test_shots = excluded.test_shots, log_loss = excluded.log_loss,
                     baseline_log_loss = excluded.baseline_log_loss, auc = excluded.auc, brier = excluded.brier,
                     goals = excluded.goals, expected_goals = excluded.expected_goals,
                     calibration = excluded.calibration, r2_key = excluded.r2_key, active = excluded.active""",
                (version, args.train, args.test, len(y_train), len(y_test), result["log_loss"],
                 result["baseline_log_loss"], result["auc"], result["brier"], result["goals"],
                 result["expected_goals"], json.dumps(result["calibration"]), key, args.activate),
            )
        print(f"saved {version} to R2 at {key}{' and activated it' if args.activate else ''}")


def _put_bytes(key: str, body: bytes) -> None:
    if not archive.configured():
        raise archive.ArchiveUnavailable("R2 credentials are needed to store the model")
    archive._s3().put_object(Bucket=os.environ["R2_BUCKET_RAW"], Key=key, Body=body,
                             ContentType="application/octet-stream")


if __name__ == "__main__":
    main()
