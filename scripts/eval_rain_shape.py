#!/usr/bin/env python3
"""비가 '어떻게' 왔는지가 값을 하는가. 트랜스포머 가설의 싸구려 판본.

레이더는 5 분 간격 288 단계인데 우리는 합계 다섯 개만 쓴다. 288 개를 다루려면
순서를 읽는 모델이 필요하고 그것은 며칠짜리 일이다. 그 전에 손으로 만든 숫자
다섯 개로 같은 가설을 시험한다 -- 여기서 안 오르면 288 단계를 넣어도 거의
확실히 안 오른다.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_flood_map_national import USE, MODEL_KW      # noqa: E402

SHAPE = ["rain_peak5", "rain_peak60", "rain_wet_min", "rain_to_peak", "rain_burst"]


def capture(y, p, frac=0.05):
    k = max(int(round(len(p) * frac)), 1)
    return float(np.asarray(y)[np.argsort(-p)[:k]].sum()) / max(float(np.sum(y)), 1.0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_shape.csv")
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "outputs/flooded-building-register/rain_shape.json")
    a = ap.parse_args()

    d = pd.read_csv(a.table, usecols=sorted({*USE, *SHAPE, "event", "flooded"}),
                    dtype={"event": str})
    sh = d[d.flooded == 1].groupby("event").rain_6h.apply(lambda s: (s < 1).mean())
    d = d[~d.event.isin(sh[sh >= 0.5].index)]
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    d = d.dropna(subset=list(USE))
    print(f"행 {len(d):,}  침수 {int(d.flooded.sum()):,}  폭풍 {d.event.nunique()}개")

    ev = d.groupby("event").flooded.sum().sort_values(ascending=False)
    fold, load = {}, np.zeros(a.folds)
    for e, n in ev.items():
        i = int(np.argmin(load)); fold[e] = i; load[i] += n
    d["fold"] = d.event.map(fold)

    sets = {"기존 21개": list(USE), "+비의 시간모양 5열": list(USE) + SHAPE}
    res = {k: [] for k in sets}
    t0 = time.time()
    for f in range(a.folds):
        tr, te = d[d.fold != f], d[d.fold == f]
        if te.flooded.sum() == 0:
            continue
        for name, use in sets.items():
            pos = max(int(tr.flooded.sum()), 1)
            m = XGBClassifier(eval_metric="logloss", n_jobs=a.jobs,
                              scale_pos_weight=(len(tr) - pos) / pos, **MODEL_KW)
            m.fit(tr[use], tr.flooded)
            p = m.predict_proba(te[use])[:, 1]
            res[name].append({"auc": float(roc_auc_score(te.flooded, p)),
                              "top5": float(capture(te.flooded, p)) * 100})
            r = res[name][-1]
            print(f"  묶음 {f+1} {name:<16} AUC {r['auc']:.4f}  상위5% {r['top5']:5.1f}%  "
                  f"({(time.time()-t0)/60:.0f}분)", flush=True)

    print("\n=== 결과 ===")
    for k, v in res.items():
        print(f"  {k:<16} AUC {np.mean([x['auc'] for x in v]):.4f}   "
              f"상위5% {np.mean([x['top5'] for x in v]):5.1f}%")
    d5 = np.array([x["top5"] for x in res["+비의 시간모양 5열"]]) - \
         np.array([x["top5"] for x in res["기존 21개"]])
    se = d5.std(ddof=1) / np.sqrt(len(d5))
    v = "채택" if d5.mean() > 2*se else ("기각" if d5.mean() < -2*se else "판정불가")
    print(f"\n  \033[1m상위5% {d5.mean():+.2f}p ± {se:.2f}\033[0m   "
          f"이긴 묶음 {int((d5>0).sum())}/{len(d5)}  -> {v}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
