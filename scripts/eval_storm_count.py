#!/usr/bin/env python3
"""폭풍을 늘린 것이 정말 성능을 올렸는가. 시험지를 같게 놓고 다시 잰다.

어제 30 개 폭풍으로 상위 5% 포착 33.8%, 오늘 77 개로 48.0% 가 나왔다. 그런데
두 실험은 시험지가 달랐다 -- 묶음 구성이 다르니 어려운 폭풍이 어디 들어갔는지에
따라 숫자가 흔들린다. 14.2p 중 얼마가 자료가 늘어서고 얼마가 시험지가 쉬워져서인지
알 수 없다.

그래서 같은 표, 같은 묶음, 같은 시험지 위에서 학습 자료만 바꾼다.

  갑. 그 묶음을 뺀 나머지 전부로 학습          (폭풍 약 64 개)
  을. 그중 원래 쓰던 30 개에 해당하는 것만으로 학습 (폭풍 약 25 개)

시험지가 완전히 같으므로 차이는 오직 학습에 쓴 폭풍 수에서 온다.
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


def capture(y, p, frac=0.05):
    k = max(int(round(len(p) * frac)), 1)
    return float(np.asarray(y)[np.argsort(-p)[:k]].sum()) / max(float(np.sum(y)), 1.0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_all_full.csv")
    ap.add_argument("--old-events", type=Path,
                    default=ROOT / "config/radar/original_30_events.json")
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--jobs", type=int, default=9)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "outputs/flooded-building-register/storm_count.json")
    a = ap.parse_args()

    old = set(json.loads(a.old_events.read_text()))
    d = pd.read_csv(a.table, usecols=sorted({*USE, "event", "flooded"}), dtype={"event": str})
    sh = d[d.flooded == 1].groupby("event").rain_6h.apply(lambda s: (s < 1).mean())
    d = d[~d.event.isin(sh[sh >= 0.5].index)]
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    d = d.dropna(subset=list(USE))
    ev = d.groupby("event").flooded.sum().sort_values(ascending=False)
    fold, load = {}, np.zeros(a.folds)
    for e, n in ev.items():
        i = int(np.argmin(load)); fold[e] = i; load[i] += n
    d["fold"] = d.event.map(fold)
    print(f"행 {len(d):,}  폭풍 {d.event.nunique()}개  (그중 원래 쓰던 것 "
          f"{len(set(d.event) & old)}개)\n")

    res = {"전부": [], "원래 30개만": []}
    t0 = time.time()
    for f in range(a.folds):
        te = d[d.fold == f]
        if te.flooded.sum() == 0:
            continue
        full = d[d.fold != f]
        subs = full[full.event.isin(old)]
        for name, tr in (("전부", full), ("원래 30개만", subs)):
            pos = max(int(tr.flooded.sum()), 1)
            m = XGBClassifier(eval_metric="logloss", n_jobs=a.jobs,
                              scale_pos_weight=(len(tr) - pos) / pos, **MODEL_KW)
            m.fit(tr[USE], tr.flooded)
            p = m.predict_proba(te[USE])[:, 1]
            res[name].append({"auc": float(roc_auc_score(te.flooded, p)),
                              "top5": float(capture(te.flooded, p)) * 100,
                              "storms": int(tr.event.nunique()), "rows": int(len(tr))})
            r = res[name][-1]
            print(f"  묶음 {f+1} {name:<12} 폭풍 {r['storms']:2d}개 {r['rows']:>10,}행  "
                  f"AUC {r['auc']:.4f}  상위5% {r['top5']:5.1f}%  ({(time.time()-t0)/60:.0f}분)",
                  flush=True)

    print("\n=== 같은 시험지 위에서 ===")
    for name, v in res.items():
        print(f"  {name:<12} AUC {np.mean([x['auc'] for x in v]):.4f}   "
              f"상위5% {np.mean([x['top5'] for x in v]):5.1f}%   "
              f"평균 폭풍 {np.mean([x['storms'] for x in v]):.0f}개")
    da = np.array([x["top5"] for x in res["전부"]]) - \
         np.array([x["top5"] for x in res["원래 30개만"]])
    se = da.std(ddof=1) / np.sqrt(len(da))
    print(f"\n  \033[1m폭풍을 늘린 효과: 상위5% {da.mean():+.2f}p ± {se:.2f}\033[0m"
          f"   이긴 묶음 {int((da>0).sum())}/{len(da)}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
