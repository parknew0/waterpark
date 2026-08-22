#!/usr/bin/env python3
"""Diagnose whether the model is actually fitting, or memorising.

The design comparison reported a positives-weighted PR-AUC of 0.1329 without
ever checking the training score, and the gap turns out to matter: at 400
trees the model scores 0.4305 on its own training provinces against 0.1975
on Gyeongbuk, and pushing to 1500 trees widens that to 0.6547 against 0.2154.
Training performance climbs while held-out performance barely moves, which is
the signature of memorising rather than learning.

Three things go unmeasured until now and are measured here:

* the tree count was set to 400 by hand, never searched, so the learning
  curve is traced per province instead of assumed;
* early stopping was never used, so every run built all 400 trees whether or
  not they helped -- and the validation set it needs must be a *different
  province*, since a random split shares neighbourhoods with training and
  would stop far too late;
* rows are treated as independent when they are not.  Buildings on the same
  street share terrain, so 49,738 rows carry far less information than the
  count suggests.  Blocking by 시군구 measures what that costs.

Every number is compared against the rule on identical rows, because a model
that cannot beat one column should lose to it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compare_flood_model_designs import (
    ELEVATION,
    RULE_FEATURE,
    add_ranks,
    column_score,
    labels_of,
    load_rows,
    matrix,
)
from data_paths import ROOT

INTERIM = ROOT / "data/interim/vworld-buildings"
OUT_DIR = ROOT / "outputs/flooded-building-register"

TREE_COUNTS = [25, 50, 100, 200, 400, 800, 1600]
BASE_PARAMS = {
    "max_depth": 5,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 20,
    "reg_lambda": 5.0,
}


def make_model(n_estimators: int, pos_weight: float, **overrides):
    from xgboost import XGBClassifier

    params = dict(BASE_PARAMS)
    params.update(overrides)
    return XGBClassifier(
        n_estimators=n_estimators,
        scale_pos_weight=pos_weight,
        eval_metric="aucpr",
        tree_method="hist",
        random_state=0,
        n_jobs=4,
        **params,
    )


def pos_weight_of(y: np.ndarray, w: np.ndarray) -> float:
    return float(np.sum(w[y == 0])) / max(float(np.sum(w[y == 1])), 1.0)


def ap(y, score, w) -> float:
    return float(average_precision_score(y, score, sample_weight=w))


def learning_curve(rows, feats, provinces) -> dict[str, Any]:
    """Train and held-out scores against tree count, for every province."""
    out: dict[str, Any] = {}
    for province in provinces:
        train = [r for r in rows if r["province_code"] != province]
        test = [r for r in rows if r["province_code"] == province]
        x_train, x_test = matrix(train, feats), matrix(test, feats)
        y_train, w_train = labels_of(train)
        y_test, w_test = labels_of(test)
        pw = pos_weight_of(y_train, w_train)

        curve = []
        for n in TREE_COUNTS:
            model = make_model(n, pw)
            model.fit(x_train, y_train, sample_weight=w_train, verbose=False)
            curve.append(
                {
                    "trees": n,
                    "train": round(ap(y_train, model.predict_proba(x_train)[:, 1], w_train), 4),
                    "test": round(ap(y_test, model.predict_proba(x_test)[:, 1], w_test), 4),
                }
            )
        best = max(curve, key=lambda c: c["test"])
        out[province] = {
            "curve": curve,
            "best_trees": best["trees"],
            "best_test": best["test"],
            "at_400": next(c["test"] for c in curve if c["trees"] == 400),
            "rule": round(ap(y_test, column_score(test, RULE_FEATURE), w_test), 4),
        }
        print(
            f"  [{province}] 최적 {best['trees']:>4}그루 {best['test']:.4f}"
            f" | 400그루 {out[province]['at_400']:.4f} | 규칙 {out[province]['rule']:.4f}",
            flush=True,
        )
    return out


def early_stopping(rows, feats, provinces) -> dict[str, Any]:
    """Stop on a held-out province, never on a random slice of training rows.

    A random validation split shares streets, and often buildings on the same
    parcel, with the training rows.  Validation score then tracks training
    score, the stop never triggers, and early stopping silently does nothing.
    """
    out: dict[str, Any] = {}
    for province in provinces:
        others = [p for p in provinces if p != province]
        if not others:
            continue
        # Validate on the largest remaining province so the signal is stable.
        counts = Counter(r["province_code"] for r in rows if r["_y"] == 1)
        validation = max(others, key=lambda p: counts[p])

        train = [r for r in rows if r["province_code"] not in (province, validation)]
        valid = [r for r in rows if r["province_code"] == validation]
        test = [r for r in rows if r["province_code"] == province]
        if not train or not valid or not test:
            continue

        x_train, y_train, w_train = matrix(train, feats), *labels_of(train)
        x_valid, y_valid, w_valid = matrix(valid, feats), *labels_of(valid)
        x_test, y_test, w_test = matrix(test, feats), *labels_of(test)

        model = make_model(2000, pos_weight_of(y_train, w_train), early_stopping_rounds=50)
        model.fit(
            x_train,
            y_train,
            sample_weight=w_train,
            eval_set=[(x_valid, y_valid)],
            sample_weight_eval_set=[w_valid],
            verbose=False,
        )
        stopped = int(getattr(model, "best_iteration", 0) or 0) + 1
        out[province] = {
            "validation_province": validation,
            "stopped_at_trees": stopped,
            "test": round(ap(y_test, model.predict_proba(x_test)[:, 1], w_test), 4),
            "rule": round(ap(y_test, column_score(test, RULE_FEATURE), w_test), 4),
        }
        print(
            f"  [{province}] {stopped:>4}그루에서 정지 (검증={validation})"
            f" | 성능 {out[province]['test']:.4f} | 규칙 {out[province]['rule']:.4f}",
            flush=True,
        )
    return out


def spatial_block_cv(rows, feats, folds: int = 5) -> dict[str, Any]:
    """Hold out whole 시군구 blocks, not random rows.

    Random row splits put neighbours on both sides, so the model can reach a
    test row by recalling one across the street.  Blocking by district forces
    it to generalise to ground it has never seen.  The two numbers together
    show how much of the random-split score was neighbourhood recall.
    """
    for row in rows:
        row["_block"] = (row.get("legal_dong_code") or "")[:5] or row["province_code"]
    blocks = sorted({r["_block"] for r in rows})
    rng = np.random.default_rng(0)
    assignment = {b: int(i) for b, i in zip(blocks, rng.integers(0, folds, len(blocks)))}

    block_scores, random_scores = [], []
    order = rng.permutation(len(rows))
    for fold in range(folds):
        train = [r for r in rows if assignment[r["_block"]] != fold]
        test = [r for r in rows if assignment[r["_block"]] == fold]
        if not train or not test:
            continue
        y_test, w_test = labels_of(test)
        if y_test.sum() < 30:
            continue
        y_train, w_train = labels_of(train)
        model = make_model(400, pos_weight_of(y_train, w_train))
        model.fit(matrix(train, feats), y_train, sample_weight=w_train, verbose=False)
        block_scores.append(ap(y_test, model.predict_proba(matrix(test, feats))[:, 1], w_test))

        # Same fold size, but rows chosen at random rather than by district.
        cut = len(rows) * fold // folds, len(rows) * (fold + 1) // folds
        test_idx = set(order[cut[0] : cut[1]].tolist())
        r_train = [r for i, r in enumerate(rows) if i not in test_idx]
        r_test = [r for i, r in enumerate(rows) if i in test_idx]
        ry, rw = labels_of(r_train)
        model = make_model(400, pos_weight_of(ry, rw))
        model.fit(matrix(r_train, feats), ry, sample_weight=rw, verbose=False)
        ty, tw = labels_of(r_test)
        random_scores.append(ap(ty, model.predict_proba(matrix(r_test, feats))[:, 1], tw))
        print(
            f"  [fold {fold}] 공간블록 {block_scores[-1]:.4f} | 무작위 {random_scores[-1]:.4f}",
            flush=True,
        )

    return {
        "blocks": len(blocks),
        "spatial_block_mean": round(float(np.mean(block_scores)), 4) if block_scores else None,
        "random_split_mean": round(float(np.mean(random_scores)), 4) if random_scores else None,
        "inflation": round(float(np.mean(random_scores) / np.mean(block_scores)), 2)
        if block_scores and random_scores and np.mean(block_scores)
        else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", nargs="+", type=Path, required=True)
    parser.add_argument("--labels", nargs="+", type=Path, required=True)
    parser.add_argument("--min-test-positives", type=int, default=150)
    args = parser.parse_args()

    rows = load_rows(args.features, args.labels)
    ranks = add_ranks(rows, ELEVATION, "province")
    feats = ELEVATION + ranks
    positives = Counter(r["province_code"] for r in rows if r["_y"] == 1)
    provinces = sorted(p for p, n in positives.items() if n >= args.min_test_positives)

    print(f"[data] {len(rows):,}행 / 변수 {len(feats)}개 / 시도 {len(provinces)}개\n")

    print("[1] 학습곡선 — 트리 수에 따른 학습셋 대 홀드아웃")
    curves = learning_curve(rows, feats, provinces)

    print("\n[2] 조기 종료 — 다른 시도를 검증셋으로")
    stopping = early_stopping(rows, feats, provinces)

    print("\n[3] 공간 블록 교차검증 — 시군구 단위로 분리")
    spatial = spatial_block_cv(rows, feats)

    weights = [positives[p] for p in provinces]
    summary = {
        "at_400": np.average([curves[p]["at_400"] for p in provinces], weights=weights),
        "best_trees": np.average([curves[p]["best_test"] for p in provinces], weights=weights),
        "early_stop": np.average(
            [stopping[p]["test"] for p in provinces if p in stopping],
            weights=[positives[p] for p in provinces if p in stopping],
        )
        if stopping
        else None,
        "rule": np.average([curves[p]["rule"] for p in provinces], weights=weights),
    }

    print("\n" + "=" * 66)
    print("종합 (양성 수 가중평균)")
    print("-" * 66)
    print(f"  규칙                        {summary['rule']:.4f}")
    print(f"  XGB 400그루 (기존 보고값)     {summary['at_400']:.4f}")
    print(f"  XGB 시도별 최적 그루 수       {summary['best_trees']:.4f}")
    if summary["early_stop"] is not None:
        print(f"  XGB 조기종료                 {summary['early_stop']:.4f}")
    print("=" * 66)
    print(f"\n  시도별 최적 트리 수: {[curves[p]['best_trees'] for p in provinces]}")
    if stopping:
        print(f"  조기종료 정지 지점  : {[stopping[p]['stopped_at_trees'] for p in provinces if p in stopping]}")
    print()
    print(f"[공간 자기상관] 시군구 블록 {spatial['blocks']}개")
    print(f"  공간 블록 분할 {spatial['spatial_block_mean']}")
    print(f"  무작위 분할    {spatial['random_split_mean']}")
    if spatial["inflation"]:
        print(f"  → 무작위 분할이 {spatial['inflation']}배 부풀려짐")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "model_fitting_diagnostics.json"
    out.write_text(
        json.dumps(
            {
                "learning_curves": curves,
                "early_stopping": stopping,
                "spatial_block_cv": spatial,
                "weighted_summary": {k: (round(v, 4) if v is not None else None) for k, v in summary.items()},
                "notes": [
                    "학습셋 점수는 같은 시도로 계산하므로 성능 주장에 쓰지 않는다.",
                    "조기 종료 검증셋은 다른 시도다. 무작위 분할은 같은 동네가 양쪽에 들어간다.",
                    "공간 블록 교차검증은 시군구 단위로 나눈다.",
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
