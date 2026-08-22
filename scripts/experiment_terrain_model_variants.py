#!/usr/bin/env python3
"""Stress-test the "a single rule beats XGBoost" claim before accepting it.

One province holdout on 456 rows is a thin basis for retiring a model, and
several ordinary explanations for the gap had not been ruled out:

* noise -- Gyeongbuk contributes 175 positives, so the 0.214 against 0.188
  difference may not survive resampling;
* feature set -- distance features were measured to reverse direction between
  provinces, so they may be actively hurting transfer;
* scale -- a tree splits on absolute metres, but 15 m means "low" in Seoul
  and "typical" in Gyeongbuk, so a threshold learned in one province
  misapplies in the other;
* fitting -- depth and estimator count were picked, not tuned, and the
  training set is 61% Seoul, whose terrain signal is the weakest measured.

So every province takes a turn as the holdout, four variants are compared on
identical rows, and the headline comparison gets a bootstrap interval.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

import numpy as np
from sklearn.metrics import average_precision_score

from data_paths import ROOT

INTERIM = ROOT / "data/interim/vworld-buildings"
OUT_DIR = ROOT / "outputs/flooded-building-register"

ELEVATION_FEATURES = [
    "surface_elevation_m",
    "relative_elevation_200m_m",
    "relative_elevation_500m_m",
    "relative_elevation_1000m_m",
    "relative_elevation_2000m_m",
    "elevation_above_nearest_national_river_m",
    "elevation_above_nearest_local_river_m",
]
DISTANCE_FEATURES = [
    "distance_to_national_river_m",
    "distance_to_local_river_m",
    "distance_to_stream_m",
]
ALL_FEATURES = ELEVATION_FEATURES + DISTANCE_FEATURES
RULE_FEATURE = "relative_elevation_500m_m"

BOOTSTRAP_ROUNDS = 400


def load_rows(feature_paths: list[Path], label_paths: list[Path]) -> list[dict[str, Any]]:
    labels: dict[tuple[str, str, str], tuple[int, float]] = {}
    for path in label_paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                labels[(row["gis_building_id"], row["longitude"], row["latitude"])] = (
                    int(row["flooded"]),
                    float(row["sample_weight"]),
                )
    rows = []
    for path in feature_paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row["gis_building_id"], row["longitude"], row["latitude"])
                if key not in labels:
                    continue
                row["_y"], row["_w"] = labels[key]
                rows.append(row)
    return rows


def numeric(row: dict[str, Any], name: str) -> float:
    value = row.get(name, "")
    if value in ("", None):
        return np.nan
    try:
        return float(value)
    except ValueError:
        return np.nan


def add_province_ranks(rows: list[dict[str, Any]], features: list[str]) -> None:
    """Percentile of each feature within its own province.

    A tree splits on an absolute value, so a threshold fitted where the median
    relative elevation is 20 m does not carry to a province where it is 15 m.
    Ranking inside the province makes "bottom 10% locally" mean the same thing
    everywhere, at the cost of needing that province's distribution at
    inference time.
    """
    by_province: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_province[row["province_code"]].append(row)

    for province_rows in by_province.values():
        for name in features:
            values = np.asarray([numeric(r, name) for r in province_rows])
            finite = values[np.isfinite(values)]
            if finite.size < 10:
                for row in province_rows:
                    row[f"rank_{name}"] = ""
                continue
            order = np.argsort(np.argsort(np.where(np.isfinite(values), values, np.inf)))
            denominator = max(finite.size - 1, 1)
            for row, rank, value in zip(province_rows, order, values):
                row[f"rank_{name}"] = (
                    "" if not np.isfinite(value) else round(float(rank) / denominator, 6)
                )


def matrix(rows: list[dict[str, Any]], features: list[str]) -> np.ndarray:
    out = np.full((len(rows), len(features)), np.nan, dtype="float64")
    for index, row in enumerate(rows):
        for column, name in enumerate(features):
            out[index, column] = numeric(row, name)
    return out


def labels_of(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray([r["_y"] for r in rows], dtype="int8")
    w = np.asarray([r["_w"] for r in rows], dtype="float64")
    return y, w


def rule_score(rows: list[dict[str, Any]]) -> np.ndarray:
    values = np.asarray([-numeric(r, RULE_FEATURE) for r in rows], dtype="float64")
    if np.isnan(values).any():
        values[np.isnan(values)] = np.nanmedian(values)
    return values


def make_model(depth: int, estimators: int, seed: int, pos_weight: float):
    from xgboost import XGBClassifier

    return XGBClassifier(
        n_estimators=estimators,
        max_depth=depth,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=20,
        reg_lambda=5.0,
        scale_pos_weight=pos_weight,
        eval_metric="aucpr",
        tree_method="hist",
        random_state=seed,
        n_jobs=4,
    )


VARIANTS: dict[str, dict[str, Any]] = {
    "전체 변수 (현재)": {"features": ALL_FEATURES, "depth": 5, "estimators": 400},
    "고도만 (거리 제외)": {"features": ELEVATION_FEATURES, "depth": 5, "estimators": 400},
    "고도 + 시도내 순위": {"features": None, "depth": 5, "estimators": 400},
    "고도만 + 얕은 트리": {"features": ELEVATION_FEATURES, "depth": 3, "estimators": 200},
}


def score_variant(
    name: str,
    config: dict[str, Any],
    train_rows: list[dict[str, Any]],
    test_rows: list[dict[str, Any]],
) -> np.ndarray | None:
    features = config["features"]
    if features is None:
        features = ELEVATION_FEATURES + [f"rank_{f}" for f in ELEVATION_FEATURES]

    x_train = matrix(train_rows, features)
    x_test = matrix(test_rows, features)
    y_train, w_train = labels_of(train_rows)
    if y_train.sum() < 50:
        return None

    positives = float(np.sum(w_train[y_train == 1]))
    negatives = float(np.sum(w_train[y_train == 0]))
    model = make_model(
        config["depth"], config["estimators"], 0, negatives / max(positives, 1.0)
    )
    model.fit(x_train, y_train, sample_weight=w_train, verbose=False)
    return model.predict_proba(x_test)[:, 1]


def bootstrap_difference(
    y: np.ndarray, w: np.ndarray, a: np.ndarray, b: np.ndarray, rounds: int
) -> dict[str, float]:
    """Resample rows to see whether one score really ranks better than another."""
    rng = np.random.default_rng(0)
    diffs = []
    n = len(y)
    for _ in range(rounds):
        pick = rng.integers(0, n, n)
        if y[pick].sum() == 0 or y[pick].sum() == len(pick):
            continue
        try:
            diffs.append(
                average_precision_score(y[pick], a[pick], sample_weight=w[pick])
                - average_precision_score(y[pick], b[pick], sample_weight=w[pick])
            )
        except ValueError:
            continue
    if not diffs:
        return {}
    array = np.asarray(diffs)
    return {
        "mean_difference": round(float(array.mean()), 4),
        "ci_low": round(float(np.percentile(array, 2.5)), 4),
        "ci_high": round(float(np.percentile(array, 97.5)), 4),
        "share_model_wins": round(float((array > 0).mean()), 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", nargs="+", type=Path, required=True)
    parser.add_argument("--labels", nargs="+", type=Path, required=True)
    parser.add_argument("--min-test-positives", type=int, default=100)
    args = parser.parse_args()

    rows = load_rows(args.features, args.labels)
    if not rows:
        raise SystemExit("결합된 행이 없다")
    add_province_ranks(rows, ELEVATION_FEATURES)

    positives = Counter(r["province_code"] for r in rows if r["_y"] == 1)
    provinces = [p for p, n in positives.items() if n >= args.min_test_positives]
    print(f"[data] {len(rows):,}행 / 양성 {sum(positives.values()):,}")
    print(f"[plan] 홀드아웃 대상 시도 {len(provinces)}개: {', '.join(sorted(provinces))}\n")

    per_province: list[dict[str, Any]] = []
    for province in sorted(provinces):
        train_rows = [r for r in rows if r["province_code"] != province]
        test_rows = [r for r in rows if r["province_code"] == province]
        y_test, w_test = labels_of(test_rows)

        entry: dict[str, Any] = {
            "province": province,
            "test_rows": len(test_rows),
            "test_positives": int(y_test.sum()),
            "base_rate": round(float(np.average(y_test, weights=w_test)), 4),
        }
        rule = rule_score(test_rows)
        entry["rule"] = round(
            float(average_precision_score(y_test, rule, sample_weight=w_test)), 4
        )
        for name, config in VARIANTS.items():
            score = score_variant(name, config, train_rows, test_rows)
            entry[name] = (
                None
                if score is None
                else round(
                    float(average_precision_score(y_test, score, sample_weight=w_test)), 4
                )
            )
            if name == "고도만 (거리 제외)" and score is not None:
                entry["_boot"] = bootstrap_difference(
                    y_test, w_test, score, rule, BOOTSTRAP_ROUNDS
                )
        per_province.append(entry)
        print(f"  [{province}] 완료 (양성 {entry['test_positives']:,})", flush=True)

    names = ["rule"] + list(VARIANTS)
    header = f"{'시도':<8}{'양성':>7}{'기준선':>9}" + "".join(
        f"{n[:14]:>16}" for n in names
    )
    print()
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for entry in per_province:
        line = f"{entry['province']:<8}{entry['test_positives']:>7,}{entry['base_rate']:>9.4f}"
        for name in names:
            value = entry.get(name)
            line += f"{(f'{value:.4f}' if value is not None else '—'):>16}"
        print(line)
    print("-" * len(header))
    mean_line = f"{'평균':<8}{'':>7}{'':>9}"
    for name in names:
        values = [e[name] for e in per_province if e.get(name) is not None]
        mean_line += f"{(f'{np.mean(values):.4f}' if values else '—'):>16}"
    print(mean_line)
    print("=" * len(header))

    print("\n[부트스트랩] '고도만' 모델 − 규칙, 시도별 신뢰구간")
    for entry in per_province:
        boot = entry.get("_boot") or {}
        if not boot:
            continue
        print(
            f"  {entry['province']}: 차이 {boot['mean_difference']:+.4f}"
            f"  95% CI [{boot['ci_low']:+.4f}, {boot['ci_high']:+.4f}]"
            f"  모델 우세 비율 {boot['share_model_wins']:.0%}"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "terrain_model_variants.json"
    out.write_text(
        json.dumps(
            {"variants": {k: {kk: vv for kk, vv in v.items() if kk != "features"} for k, v in VARIANTS.items()},
             "rule_feature": RULE_FEATURE,
             "per_province": per_province,
             "notes": [
                 "각 시도를 완전히 제외하고 학습한 뒤 그 시도로 평가한다.",
                 "부트스트랩 CI가 0을 포함하면 두 방식의 차이는 표본 잡음과 구분되지 않는다.",
                 "시도내 순위 변수는 예측 시점에 해당 시도 분포표가 필요하다.",
             ]},
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
