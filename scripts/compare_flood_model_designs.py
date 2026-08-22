#!/usr/bin/env python3
"""Compare every design worth trying, on one honest evaluation.

The earlier run tested four variants against one rule and drew its
conclusion from a single province with 175 positives, where the bootstrap
interval spanned zero.  This widens both sides of that comparison.

Fairness first: the rule gets rank-normalised too.  Ranking was introduced
to fix a real problem -- a tree splits on absolute metres, and 15 m means
"low" in Seoul but "typical" in Gyeongbuk -- and that problem applies just
as much to a fixed threshold on one column.  Giving the treatment only to
the model would manufacture the win.

Ranks are also tried at 시군구 rather than 시도 granularity, since Seoul's
25 boroughs sit on quite different ground, and building attributes join the
feature set because underground floor count and use were collected but never
offered to the model.

Every design is scored by leave-one-province-out: each province is held out
entirely, the rest trains, and results are reported per province plus two
aggregates.  The plain mean weights a 175-positive province like a
9,498-positive one, so a positives-weighted mean is shown beside it, along
with lift over each province's own base rate.

Selecting the best row of this table is mildly optimistic -- the same
evaluation both tuned and ranked the designs -- so the winner needs a fresh
holdout before any performance claim.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

import numpy as np
from sklearn.metrics import average_precision_score

from data_paths import ROOT

OUT_DIR = ROOT / "outputs/flooded-building-register"

ELEVATION = [
    "surface_elevation_m",
    "relative_elevation_200m_m",
    "relative_elevation_500m_m",
    "relative_elevation_1000m_m",
    "relative_elevation_2000m_m",
    "elevation_above_nearest_national_river_m",
    "elevation_above_nearest_local_river_m",
]
DISTANCE = [
    "distance_to_national_river_m",
    "distance_to_local_river_m",
    "distance_to_stream_m",
]
BUILDING = ["underground_floor_count", "building_use_code"]
RULE_FEATURE = "relative_elevation_500m_m"

BOOTSTRAP_ROUNDS = 300


def numeric(row: dict[str, Any], name: str) -> float:
    value = row.get(name, "")
    if value in ("", None):
        return np.nan
    try:
        return float(value)
    except ValueError:
        return np.nan


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
    rows: list[dict[str, Any]] = []
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


def add_ranks(rows: list[dict[str, Any]], features: list[str], level: str) -> list[str]:
    """Percentile of each feature within its own province or 시군구.

    Computed from building geometry only, never from labels, so this is not
    leakage -- but it does mean the deployed service must carry the same
    distribution table to convert a new point into a rank.
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            row["province_code"]
            if level == "province"
            else (row.get("legal_dong_code") or "")[:5] or row["province_code"]
        )
        groups[key].append(row)

    suffix = "prov" if level == "province" else "sgg"
    names = [f"rank_{suffix}_{f}" for f in features]
    for group_rows in groups.values():
        for feature, column in zip(features, names):
            values = np.asarray([numeric(r, feature) for r in group_rows])
            finite = values[np.isfinite(values)]
            if finite.size < 10:
                for row in group_rows:
                    row[column] = ""
                continue
            filled = np.where(np.isfinite(values), values, np.inf)
            order = np.argsort(np.argsort(filled))
            denominator = max(finite.size - 1, 1)
            for row, rank, value in zip(group_rows, order, values):
                row[column] = (
                    "" if not np.isfinite(value) else round(float(rank) / denominator, 6)
                )
    return names


def matrix(rows: list[dict[str, Any]], features: list[str]) -> np.ndarray:
    out = np.full((len(rows), len(features)), np.nan, dtype="float64")
    for index, row in enumerate(rows):
        for column, name in enumerate(features):
            out[index, column] = numeric(row, name)
    return out


def labels_of(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    return (
        np.asarray([r["_y"] for r in rows], dtype="int8"),
        np.asarray([r["_w"] for r in rows], dtype="float64"),
    )


def column_score(rows: list[dict[str, Any]], column: str) -> np.ndarray:
    """Lower ground ranks as higher risk, so negate; missing sits at median."""
    values = np.asarray([-numeric(r, column) for r in rows], dtype="float64")
    if np.isnan(values).any():
        values[np.isnan(values)] = np.nanmedian(values)
    return values


def fit_predict(
    train_rows: list[dict[str, Any]],
    test_rows: list[dict[str, Any]],
    features: list[str],
    params: dict[str, Any],
) -> np.ndarray:
    from xgboost import XGBClassifier

    x_train = matrix(train_rows, features)
    x_test = matrix(test_rows, features)
    y_train, w_train = labels_of(train_rows)
    positives = float(np.sum(w_train[y_train == 1]))
    negatives = float(np.sum(w_train[y_train == 0]))
    model = XGBClassifier(
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=negatives / max(positives, 1.0),
        eval_metric="aucpr",
        tree_method="hist",
        random_state=0,
        n_jobs=4,
        **params,
    )
    model.fit(x_train, y_train, sample_weight=w_train, verbose=False)
    return model.predict_proba(x_test)[:, 1]


def rank_of(score: np.ndarray) -> np.ndarray:
    """Rank transform so scores on different scales can be averaged."""
    order = np.argsort(np.argsort(score))
    return order / max(len(score) - 1, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", nargs="+", type=Path, required=True)
    parser.add_argument("--labels", nargs="+", type=Path, required=True)
    parser.add_argument("--min-test-positives", type=int, default=150)
    args = parser.parse_args()

    rows = load_rows(args.features, args.labels)
    if not rows:
        raise SystemExit("결합된 행이 없다")

    rank_prov = add_ranks(rows, ELEVATION, "province")
    rank_sgg = add_ranks(rows, ELEVATION, "sigungu")

    base_params = {"n_estimators": 400, "max_depth": 5, "learning_rate": 0.05,
                   "min_child_weight": 20, "reg_lambda": 5.0}
    deep = {"n_estimators": 800, "max_depth": 7, "learning_rate": 0.03,
            "min_child_weight": 10, "reg_lambda": 2.0}
    strong_reg = {"n_estimators": 600, "max_depth": 4, "learning_rate": 0.05,
                  "min_child_weight": 50, "reg_lambda": 20.0}

    designs: dict[str, dict[str, Any]] = {
        "규칙 원본": {"kind": "column", "column": RULE_FEATURE},
        "규칙 시도순위": {"kind": "column", "column": f"rank_prov_{RULE_FEATURE}"},
        "규칙 시군구순위": {"kind": "column", "column": f"rank_sgg_{RULE_FEATURE}"},
        "XGB 고도": {"kind": "model", "features": ELEVATION, "params": base_params},
        "XGB 고도+거리": {"kind": "model", "features": ELEVATION + DISTANCE, "params": base_params},
        "XGB 시도순위": {"kind": "model", "features": ELEVATION + rank_prov, "params": base_params},
        "XGB 시군구순위": {"kind": "model", "features": ELEVATION + rank_sgg, "params": base_params},
        "XGB 시군구+건물": {"kind": "model", "features": ELEVATION + rank_sgg + BUILDING, "params": base_params},
        "XGB 시군구 깊게": {"kind": "model", "features": ELEVATION + rank_sgg, "params": deep},
        "XGB 시군구 강규제": {"kind": "model", "features": ELEVATION + rank_sgg, "params": strong_reg},
        "앙상블 규칙+XGB": {"kind": "ensemble"},
    }

    positives = Counter(r["province_code"] for r in rows if r["_y"] == 1)
    provinces = sorted(p for p, n in positives.items() if n >= args.min_test_positives)
    print(f"[data] {len(rows):,}행 / 양성 {sum(positives.values()):,}")
    print(f"[plan] 시도 {len(provinces)}개 × 설계 {len(designs)}개\n")

    table: dict[str, dict[str, float]] = defaultdict(dict)
    meta: dict[str, dict[str, Any]] = {}

    for province in provinces:
        train_rows = [r for r in rows if r["province_code"] != province]
        test_rows = [r for r in rows if r["province_code"] == province]
        y_test, w_test = labels_of(test_rows)
        base = float(np.average(y_test, weights=w_test))
        meta[province] = {
            "test_rows": len(test_rows),
            "test_positives": int(y_test.sum()),
            "base_rate": round(base, 4),
        }

        cached: dict[str, np.ndarray] = {}
        for name, design in designs.items():
            if design["kind"] == "column":
                score = column_score(test_rows, design["column"])
            elif design["kind"] == "model":
                score = fit_predict(train_rows, test_rows, design["features"], design["params"])
            else:
                # Average the two ranked scores so neither scale dominates.
                score = (
                    rank_of(cached["규칙 시군구순위"]) + rank_of(cached["XGB 시군구순위"])
                ) / 2.0
            cached[name] = score
            table[name][province] = float(
                average_precision_score(y_test, score, sample_weight=w_test)
            )
        print(f"  [{province}] 완료 (양성 {meta[province]['test_positives']:,})", flush=True)

    order = sorted(
        designs,
        key=lambda n: -np.average(
            [table[n][p] for p in provinces],
            weights=[meta[p]["test_positives"] for p in provinces],
        ),
    )

    width = 18 + 9 * len(provinces) + 22
    print()
    print("=" * width)
    header = f"{'설계':<18}" + "".join(f"{p:>9}" for p in provinces) + f"{'단순평균':>11}{'가중평균':>11}"
    print(header)
    print("-" * width)
    print(
        f"{'(기준선)':<18}"
        + "".join(f"{meta[p]['base_rate']:>9.4f}" for p in provinces)
        + f"{'':>22}"
    )
    print("-" * width)
    for name in order:
        values = [table[name][p] for p in provinces]
        weights = [meta[p]["test_positives"] for p in provinces]
        line = f"{name:<18}" + "".join(f"{v:>9.4f}" for v in values)
        line += f"{np.mean(values):>11.4f}{np.average(values, weights=weights):>11.4f}"
        print(line)
    print("=" * width)

    print("\n[기준선 대비 배수] 각 시도 자체 양성비율로 나눈 값")
    print(f"{'설계':<18}{'단순평균':>11}{'가중평균':>11}")
    print("-" * 40)
    lift_order = []
    for name in order:
        lifts = [table[name][p] / meta[p]["base_rate"] for p in provinces]
        weights = [meta[p]["test_positives"] for p in provinces]
        lift_order.append((np.average(lifts, weights=weights), name, np.mean(lifts)))
    for weighted, name, simple in sorted(lift_order, reverse=True):
        print(f"{name:<18}{simple:>11.2f}{weighted:>11.2f}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "flood_model_design_comparison.json"
    out.write_text(
        json.dumps(
            {
                "provinces": meta,
                "pr_auc": {n: {p: round(v, 4) for p, v in table[n].items()} for n in designs},
                "notes": [
                    "각 시도를 완전히 제외하고 학습한 뒤 그 시도로 평가한다.",
                    "순위 변수는 건물 기하만으로 계산하며 라벨을 쓰지 않는다.",
                    "이 표에서 최고를 고르는 것은 낙관적이다. 확정 전 새 홀드아웃이 필요하다.",
                    "라벨은 지표면 침수이며 지하주차장 침수가 아니다.",
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
