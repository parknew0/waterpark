#!/usr/bin/env python3
"""다른 알고리즘도 같은 자료에서 재본다. 그리고 섞으면 나아지는지.

XGBoost 하나만 써 왔다. LightGBM 과 CatBoost 는 같은 부스팅 계열이지만 나무를
키우는 방식이 다르다 -- XGBoost 는 깊이를 맞춰 넓히고, LightGBM 은 이득이 큰 잎부터
쪼갠다. 어느 쪽이 이 문제에 맞는지는 재봐야 안다.

섞는 것도 같이 본다. 서로 다른 실수를 하는 모델을 평균하면 대개 하나보다 낫다.
순위만 쓰므로 확률을 그대로 더하지 않고 \033[1m순위를 평균\033[0m 한다 -- 세 모델의 확률
눈금이 서로 달라서, 그대로 더하면 눈금이 큰 모델이 판을 지배한다.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_flood_map_national import USE, MODEL_KW      # noqa: E402
from eval_hyper_sweep import prep, capture              # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_146.csv")
    ap.add_argument("--sample", type=float, default=0.35)
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "outputs/flooded-building-register/libraries.json")
    a = ap.parse_args()

    from xgboost import XGBClassifier
    import lightgbm as lgb
    from catboost import CatBoostClassifier

    d = prep(a.table, a.sample, a.folds)
    print(f"행 {len(d):,}  침수 {int(d.flooded.sum()):,}  폭풍 {d.event.nunique()}개\n")

    res = {k: [] for k in ("XGBoost", "LightGBM", "CatBoost", "셋 섞기(순위 평균)")}
    t0 = time.time()
    for f in range(a.folds):
        tr, te = d[d.fold != f], d[d.fold == f]
        if te.flooded.sum() == 0:
            continue
        pos = max(int(tr.flooded.sum()), 1)
        w = (len(tr) - pos) / pos
        preds = {}

        m = XGBClassifier(eval_metric="logloss", n_jobs=a.jobs, scale_pos_weight=w, **MODEL_KW)
        m.fit(tr[USE], tr.flooded)
        preds["XGBoost"] = m.predict_proba(te[USE])[:, 1]

        # 잎 수는 깊이 11 의 XGBoost 와 견줄 만한 크기로 잡는다
        m = lgb.LGBMClassifier(n_estimators=MODEL_KW["n_estimators"], num_leaves=255,
                               learning_rate=MODEL_KW["learning_rate"],
                               subsample=MODEL_KW["subsample"], subsample_freq=1,
                               colsample_bytree=MODEL_KW["colsample_bytree"],
                               min_child_samples=MODEL_KW["min_child_weight"],
                               reg_lambda=MODEL_KW["reg_lambda"],
                               scale_pos_weight=w, n_jobs=a.jobs, verbose=-1)
        m.fit(tr[USE], tr.flooded)
        preds["LightGBM"] = m.predict_proba(te[USE])[:, 1]

        m = CatBoostClassifier(iterations=MODEL_KW["n_estimators"], depth=8,
                               learning_rate=MODEL_KW["learning_rate"],
                               l2_leaf_reg=MODEL_KW["reg_lambda"],
                               scale_pos_weight=w, thread_count=a.jobs, verbose=0,
                               allow_writing_files=False)
        m.fit(tr[USE], tr.flooded)
        preds["CatBoost"] = m.predict_proba(te[USE])[:, 1]

        preds["셋 섞기(순위 평균)"] = np.mean([rankdata(v) / len(v) for v in
                                          (preds["XGBoost"], preds["LightGBM"],
                                           preds["CatBoost"])], axis=0)
        for k, p in preds.items():
            res[k].append({"auc": float(roc_auc_score(te.flooded, p)),
                           "top5": float(capture(te.flooded, p)) * 100})
        print(f"  묶음 {f+1}/{a.folds}  " +
              "  ".join(f"{k.split('(')[0]} {res[k][-1]['top5']:.1f}" for k in res) +
              f"  ({(time.time()-t0)/60:.0f}분)", flush=True)

    print("\n=== 결과 ===")
    for k, v in res.items():
        print(f"  {k:<18} AUC {np.mean([x['auc'] for x in v]):.4f}   "
              f"상위5% {np.mean([x['top5'] for x in v]):5.1f}%")
    base = np.array([x["top5"] for x in res["XGBoost"]])
    print("\n=== XGBoost 대비 (같은 묶음끼리) ===")
    for k in list(res)[1:]:
        dd = np.array([x["top5"] for x in res[k]]) - base
        se = dd.std(ddof=1) / np.sqrt(len(dd))
        v = "낫다" if dd.mean() > 2*se else ("못하다" if dd.mean() < -2*se else "판정불가")
        print(f"  {k:<18} {dd.mean():+.2f}p ± {se:.2f}   이긴 묶음 {int((dd>0).sum())}/{len(dd)}  -> {v}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
