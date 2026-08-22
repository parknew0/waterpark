#!/usr/bin/env python3
"""Test whether XGBoost now beats the single terrain rule, region by region.

The earlier attempt did not.  Split by storm group, XGBoost reached PR-AUC
0.126 against a 0.065 base rate while the one rule "ground lower than its
surroundings floods more" reached about 0.25 with nothing fitted, so the
shipped risk score is that rule and not a model.

Three things have changed since, and each one addresses a stated cause of
that failure:

* independent events: 13 derived storm groups in Gyeongbuk against 213
  distinct flood start dates nationwide;
* positives: 2,993 against 19,745;
* features: terrain at four radii instead of one, plus height above and
  distance to rivers by grade.

So the question is worth re-asking, but only under the split that matters.
Training and testing inside one province measures interpolation across a
single region's terrain; the plan is to learn where data is plentiful and
apply it to Gyeongbuk, so the province holdout is the honest test and the
random split is reported alongside purely to show the gap between them.

The rule baseline is evaluated on identical rows.  A model that cannot beat
one column deserves to lose to it.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

from data_paths import ROOT

INTERIM = ROOT / "data/interim/vworld-buildings"
OUT_DIR = ROOT / "outputs/flooded-building-register"

# Terrain and river only.  Rainfall is deliberately absent: the 06 analysis
# measured a non-monotonic flood rate against rainfall and concluded the
# event count cannot support a learned rain relationship, and nationwide
# rainfall has not been collected for the 213 event dates anyway.
FEATURES = [
    "surface_elevation_m",
    "relative_elevation_200m_m",
    "relative_elevation_500m_m",
    "relative_elevation_1000m_m",
    "relative_elevation_2000m_m",
    "distance_to_national_river_m",
    "distance_to_local_river_m",
    "distance_to_stream_m",
    "elevation_above_nearest_national_river_m",
    "elevation_above_nearest_local_river_m",
]
# Measured as inconsistent across provinces (AUC 0.471 in Seoul, 0.301 in
# Gyeongbuk) and 51.9% negative, because Euclidean nearest-neighbour finds an
# upstream mountain creek rather than the drainage a building drains toward.
EXCLUDED = ["elevation_above_nearest_stream_m"]

# The rule the model has to beat, and the direction that counts as risk.
RULE_FEATURE = "relative_elevation_500m_m"


def load_rows(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            print(f"[skip] {path} 없음", file=sys.stderr)
            continue
        with path.open(encoding="utf-8") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def attach_labels(feature_rows: list[dict[str, Any]], label_paths: list[Path]) -> list[dict[str, Any]]:
    """Join features back to labels on identity plus position."""
    labels: dict[tuple[str, str, str], tuple[int, float]] = {}
    for row in load_rows(label_paths):
        key = (row["gis_building_id"], row["longitude"], row["latitude"])
        labels[key] = (int(row["flooded"]), float(row["sample_weight"]))

    joined = []
    for row in feature_rows:
        key = (row["gis_building_id"], row["longitude"], row["latitude"])
        if key not in labels:
            continue
        flooded, weight = labels[key]
        row["_y"] = flooded
        row["_w"] = weight
        joined.append(row)
    return joined


def to_matrix(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    matrix = np.full((len(rows), len(FEATURES)), np.nan, dtype="float64")
    for index, row in enumerate(rows):
        for column, name in enumerate(FEATURES):
            value = row.get(name, "")
            if value not in ("", None):
                try:
                    matrix[index, column] = float(value)
                except ValueError:
                    pass
    y = np.asarray([r["_y"] for r in rows], dtype="int8")
    w = np.asarray([r["_w"] for r in rows], dtype="float64")
    return matrix, y, w


def rule_scores(rows: list[dict[str, Any]]) -> np.ndarray:
    """Lower ground scores higher, so negate; missing sits at median risk."""
    values = []
    for row in rows:
        raw = row.get(RULE_FEATURE, "")
        try:
            values.append(-float(raw))
        except (TypeError, ValueError):
            values.append(np.nan)
    array = np.asarray(values, dtype="float64")
    if np.isnan(array).any():
        array[np.isnan(array)] = np.nanmedian(array)
    return array


def evaluate(y: np.ndarray, w: np.ndarray, score: np.ndarray) -> dict[str, float]:
    if y.sum() == 0 or y.sum() == len(y):
        return {}
    return {
        "pr_auc": round(float(average_precision_score(y, score, sample_weight=w)), 4),
        "roc_auc": round(float(roc_auc_score(y, score, sample_weight=w)), 4),
        "base_rate": round(float(np.average(y, weights=w)), 4),
    }


def fit_model(x: np.ndarray, y: np.ndarray, w: np.ndarray, seed: int = 0):
    from xgboost import XGBClassifier

    positives = float(np.sum(w[y == 1]))
    negatives = float(np.sum(w[y == 0]))
    model = XGBClassifier(
        n_estimators=400,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        reg_lambda=1.0,
        # The weighted classes are far from balanced; without this the model
        # optimises the majority and predicts almost nothing positive.
        scale_pos_weight=negatives / max(positives, 1.0),
        eval_metric="aucpr",
        tree_method="hist",
        random_state=seed,
        n_jobs=4,
    )
    model.fit(x, y, sample_weight=w, verbose=False)
    return model


def run_split(
    name: str,
    train_rows: list[dict[str, Any]],
    test_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    x_train, y_train, w_train = to_matrix(train_rows)
    x_test, y_test, w_test = to_matrix(test_rows)
    if y_train.sum() < 20 or y_test.sum() < 20:
        return {"split": name, "skipped": "양성 표본 부족"}

    model = fit_model(x_train, y_train, w_train)
    model_score = model.predict_proba(x_test)[:, 1]

    result = {
        "split": name,
        "train_rows": len(train_rows),
        "train_positives": int(y_train.sum()),
        "test_rows": len(test_rows),
        "test_positives": int(y_test.sum()),
        "xgboost": evaluate(y_test, w_test, model_score),
        "rule": evaluate(y_test, w_test, rule_scores(test_rows)),
        "importance": dict(
            sorted(
                zip(FEATURES, (float(v) for v in model.feature_importances_)),
                key=lambda kv: -kv[1],
            )[:6]
        ),
    }
    return result


def report(results: list[dict[str, Any]]) -> None:
    print()
    print("=" * 78)
    print(f"{'분할':<26}{'양성':>8}{'기준선':>9}{'규칙 PR':>10}{'XGB PR':>10}{'판정':>12}")
    print("-" * 78)
    for item in results:
        if item.get("skipped"):
            print(f"{item['split']:<26}{item['skipped']:>50}")
            continue
        rule = item["rule"].get("pr_auc")
        xgb = item["xgboost"].get("pr_auc")
        base = item["rule"].get("base_rate")
        verdict = "XGB 승" if (xgb or 0) > (rule or 0) else "규칙 승"
        print(
            f"{item['split']:<26}{item['test_positives']:>8,}{base:>9.4f}"
            f"{rule:>10.4f}{xgb:>10.4f}{verdict:>12}"
        )
    print("=" * 78)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--features",
        nargs="+",
        type=Path,
        default=[INTERIM / "labeled_building_sample_features.csv"],
    )
    parser.add_argument(
        "--labels",
        nargs="+",
        type=Path,
        default=[INTERIM / "labeled_building_sample.csv"],
    )
    parser.add_argument("--holdout", default="47", help="province code held out entirely")
    args = parser.parse_args()

    rows = attach_labels(load_rows(args.features), args.labels)
    if not rows:
        raise SystemExit("라벨과 결합된 행이 없다")

    by_province = Counter(r["province_code"] for r in rows)
    positives = Counter(r["province_code"] for r in rows if r["_y"] == 1)
    print(f"[data] {len(rows):,}행 / 양성 {sum(positives.values()):,}")
    for code, count in by_province.most_common():
        print(f"  {code}: {count:,}행 (양성 {positives[code]:,})")

    results = []

    holdout = args.holdout
    train_rows = [r for r in rows if r["province_code"] != holdout]
    test_rows = [r for r in rows if r["province_code"] == holdout]
    if test_rows and train_rows:
        print(f"\n[split] 시도 홀드아웃: {holdout} 제외 학습 → {holdout} 평가", flush=True)
        results.append(run_split(f"타 시도 학습 → {holdout} 평가", train_rows, test_rows))

    # Reported for contrast only: a random split lets the same province sit on
    # both sides, which is the optimistic number, not the deployable one.
    rng = np.random.default_rng(0)
    order = rng.permutation(len(rows))
    cut = int(len(rows) * 0.7)
    print("[split] 무작위 분할 (참고용, 낙관적 수치)", flush=True)
    results.append(
        run_split(
            "무작위 분할 (참고)",
            [rows[i] for i in order[:cut]],
            [rows[i] for i in order[cut:]],
        )
    )

    report(results)

    for item in results:
        if item.get("skipped"):
            continue
        print(f"\n[{item['split']}] 상위 기여 변수")
        for name, value in item["importance"].items():
            print(f"  {value:.3f}  {name}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "terrain_model_comparison.json"
    out.write_text(
        json.dumps(
            {
                "features": FEATURES,
                "excluded_features": EXCLUDED,
                "rule_feature": RULE_FEATURE,
                "province_rows": dict(by_province),
                "province_positives": dict(positives),
                "results": results,
                "notes": [
                    "라벨은 지표면 침수이며 지하주차장 침수가 아니다.",
                    "강수 변수는 넣지 않았다. 전국 213개 사건의 강수를 아직 수집하지 않았다.",
                    "무작위 분할은 같은 시도가 학습·평가 양쪽에 들어가므로 배포 성능이 아니다.",
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\n저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
