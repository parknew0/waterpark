#!/usr/bin/env python3
"""Train and honestly evaluate the surface-flood model.

Leakage rules applied here
--------------------------
1. ``distance_to_flood_polygon_m`` is DROPPED. It is 0 for every positive by
   construction, so it is the label in disguise.
2. Longitude and latitude are DROPPED. The same building appears in several
   events, so coordinates let the model memorise "this exact spot floods" and
   that memory survives an event-based split.
3. Splits are never random. Timestamp-level records from the same storm are
   kept together with ``storm_group_id``; we additionally report a
   building-disjoint split, because a building present in both train and test
   leaks its terrain.

Metrics: accuracy is meaningless at a 6.5% positive rate, so we report PR-AUC,
ROC-AUC, precision and recall, plus a terrain-only baseline for comparison.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_fscore_support, roc_auc_score
from sklearn.model_selection import GroupKFold
from xgboost import XGBClassifier

from data_paths import PROCESSED_ML_TRAINING, ROOT

TABLE = PROCESSED_ML_TRAINING / "gyeongbuk_flood_training_table.csv"
OUT_DIR = ROOT / "outputs/gyeongbuk-flood-model"
REPORT = OUT_DIR / "model_report.json"

FEATURES = [
    "surface_elevation_m",
    "relative_elevation_m",
    "local_min_elevation_m",
    "rain_1h",
    "rain_3h",
    "rain_6h",
    "rain_12h",
    "rain_24h",
    "rain_station_distance_km",
]
LEAKY = ["distance_to_flood_polygon_m", "longitude", "latitude"]


def log(m: str) -> None:
    print(m, flush=True)


def evaluate(y_true, score, threshold=0.5) -> dict:
    pred = (score >= threshold).astype(int)
    p, r, f1, _ = precision_recall_fscore_support(
        y_true, pred, average="binary", zero_division=0
    )
    out = {
        "n": int(len(y_true)),
        "positives": int(y_true.sum()),
        "pr_auc": None,
        "roc_auc": None,
        "precision": round(float(p), 4),
        "recall": round(float(r), 4),
        "f1": round(float(f1), 4),
    }
    if 0 < y_true.sum() < len(y_true):
        out["pr_auc"] = round(float(average_precision_score(y_true, score)), 4)
        out["roc_auc"] = round(float(roc_auc_score(y_true, score)), 4)
        out["baseline_pr_auc"] = round(float(y_true.mean()), 4)
    return out


def make_model(pos_weight: float) -> XGBClassifier:
    return XGBClassifier(
        n_estimators=400,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        reg_lambda=2.0,
        scale_pos_weight=pos_weight,
        eval_metric="aucpr",
        tree_method="hist",
        random_state=42,
        n_jobs=4,
    )


def main() -> None:
    df = pd.read_csv(TABLE)
    log(f"[check] {len(df):,} rows, {int(df['flood'].sum()):,} positive ({df['flood'].mean()*100:.2f}%)")

    if "storm_group_id" not in df.columns or df["storm_group_id"].isna().any():
        raise SystemExit(
            "training table must contain a non-null storm_group_id for every row"
        )

    for col in FEATURES:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    before = len(df)
    df = df.dropna(subset=["surface_elevation_m", "rain_24h"])
    if len(df) != before:
        log(f"[warn] dropped {before - len(df)} rows missing elevation or rainfall")

    df["year"] = df["event_date"].str[:4].astype(int)
    log(f"[check] excluded as leakage: {', '.join(LEAKY)}")
    log(f"[check] features used: {', '.join(FEATURES)}")

    X = df[FEATURES].to_numpy(dtype=float)
    y = df["flood"].to_numpy(dtype=int)
    pos_weight = float((y == 0).sum() / max((y == 1).sum(), 1))
    storm_group_count = int(df["storm_group_id"].nunique())
    event_timestamp_count = int(df["event_id"].nunique())
    report: dict = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "rows": int(len(df)),
        "positive_rate": round(float(y.mean()), 4),
        "features": FEATURES,
        "excluded_as_leakage": LEAKY,
        "scale_pos_weight": round(pos_weight, 2),
        "event_timestamp_count": event_timestamp_count,
        "storm_group_count": storm_group_count,
    }

    # ---- 1. terrain-only baseline (no model) ---------------------------
    # Lower ground relative to its surroundings should flood more often.
    base_score = -df["relative_elevation_m"].fillna(df["relative_elevation_m"].median()).to_numpy()
    report["baseline_relative_elevation_only"] = evaluate(y, base_score, np.median(base_score))
    log(
        "[check] terrain-only baseline PR-AUC: "
        f"{report['baseline_relative_elevation_only']['pr_auc']}"
    )

    # ---- 2. temporal holdout: train on <=2018, test on 2019+ -----------
    tr, te = df["year"] <= 2018, df["year"] >= 2019
    log(f"\n[split] temporal  train {tr.sum():,} rows / test {te.sum():,} rows")
    if y[te.to_numpy()].sum() > 0 and y[tr.to_numpy()].sum() > 0:
        y_train = y[tr.to_numpy()]
        train_pos_weight = float(
            (y_train == 0).sum() / max((y_train == 1).sum(), 1)
        )
        m = make_model(train_pos_weight)
        m.fit(X[tr.to_numpy()], y_train)
        s = m.predict_proba(X[te.to_numpy()])[:, 1]
        report["temporal_holdout"] = evaluate(y[te.to_numpy()], s)
        report["temporal_holdout"]["train_years"] = "<=2018"
        report["temporal_holdout"]["test_years"] = ">=2019"
        log(f"[result] temporal  {json.dumps(report['temporal_holdout'], ensure_ascii=False)}")

    # ---- 3. grouped CV by independent storm proxy ----------------------
    groups = df["storm_group_id"].to_numpy()
    n_storms = len(np.unique(groups))
    folds = min(5, n_storms)
    if folds < 2:
        raise SystemExit("at least two storm_group_id values are required for GroupKFold")
    log(f"\n[split] GroupKFold by storm ({n_storms} storm groups, {folds} folds)")
    oof = np.full(len(y), np.nan)
    completed_folds = 0
    for k, (a, b) in enumerate(GroupKFold(n_splits=folds).split(X, y, groups), 1):
        if y[a].sum() == 0:
            log(f"   fold {k}: skipped because the training fold has no positives")
            continue
        m = make_model(float((y[a] == 0).sum() / max((y[a] == 1).sum(), 1)))
        m.fit(X[a], y[a])
        oof[b] = m.predict_proba(X[b])[:, 1]
        completed_folds += 1
        log(f"   fold {k}: train {len(a):,} / test {len(b):,} (test positives {int(y[b].sum())})")
    evaluated = ~np.isnan(oof)
    if not evaluated.any():
        raise SystemExit("no storm-group fold could be evaluated")
    report["grouped_cv_by_storm"] = evaluate(y[evaluated], oof[evaluated])
    report["grouped_cv_by_storm"]["storm_groups"] = n_storms
    report["grouped_cv_by_storm"]["completed_folds"] = completed_folds
    log(f"[result] storm CV  {json.dumps(report['grouped_cv_by_storm'], ensure_ascii=False)}")

    # ---- 4. building-disjoint CV ---------------------------------------
    bgroups = df["building_id"].to_numpy()
    log(f"\n[split] GroupKFold by building ({len(np.unique(bgroups)):,} buildings)")
    oofb = np.zeros(len(y))
    for k, (a, b) in enumerate(GroupKFold(n_splits=5).split(X, y, bgroups), 1):
        if y[a].sum() == 0:
            continue
        m = make_model(float((y[a] == 0).sum() / max((y[a] == 1).sum(), 1)))
        m.fit(X[a], y[a])
        oofb[b] = m.predict_proba(X[b])[:, 1]
    report["grouped_cv_by_building"] = evaluate(y, oofb)
    log(f"[result] building CV  {json.dumps(report['grouped_cv_by_building'], ensure_ascii=False)}")

    # ---- 5. feature importance from a full-data fit ---------------------
    final = make_model(pos_weight)
    final.fit(X, y)
    imp = sorted(
        zip(FEATURES, final.feature_importances_.tolist()), key=lambda t: -t[1]
    )
    report["feature_importance_gain"] = [{"feature": f, "importance": round(v, 4)} for f, v in imp]
    log("\n[check] feature importance:")
    for f, v in imp:
        log(f"   {v:7.4f}  {f}")

    positive_by_storm = df.groupby("storm_group_id")["flood"].sum()
    dominant_positive_share = float(positive_by_storm.max() / max(positive_by_storm.sum(), 1))
    report["critical_limitations"] = [
        "Target is surface flooding, NOT underground car park flooding.",
        "Storm-group CV and building CV answer different questions: the storm split "
        "estimates a new storm, while the building split estimates a new location.",
        f"The {event_timestamp_count} timestamp-level events are conservatively collapsed "
        f"into {storm_group_count} storm groups using same/consecutive dates. This grouping "
        "is derived, not an official disaster identifier.",
        f"The largest storm group contains {dominant_positive_share:.1%} of positive rows, "
        "so performance remains sensitive to a small number of storms.",
        "Negative labels are pseudo_negative_1km, not verified non-flood observations. "
        "The model is calibrated for 'near a known flood polygon', not all Gyeongbuk.",
        "Rainfall comes from the nearest station, so buildings sharing a station in one "
        "event share identical rain features.",
        "Elevation is a DSM, so it includes buildings and tree canopy.",
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"\n[check] wrote {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
