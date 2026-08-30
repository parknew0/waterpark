#!/usr/bin/env python3
"""하천 수위가 제 값을 하는가.

물리는 분명하다. 하천이 차 있으면 하수관이 물을 뱉지 못하고, 그래서 도시가
잠긴다. 침수 칸의 6시간 상승폭 중앙값이 0.56 m 로 안 잠긴 칸의 0.16 m 보다
세 배 넘게 높기도 하다.

그러나 이번 세션에서 교과서에 나오는 추가가 여섯 번 떨어졌다. 중앙값이
갈린다는 것과 이미 있는 21개 열이 못 하는 일을 한다는 것은 다른 얘기다.
하천 가까운 저지대는 dist_stream 과 rel_500m 이 이미 알고 있다.

폭풍을 여섯 묶음으로 나눠 하나씩 빼고 학습한다. 같은 폭풍의 칸들은 같은
비 안에 있으므로 행 단위로 나누면 시험지를 미리 보는 셈이 된다.
"""
from __future__ import annotations
import argparse, json, time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
import sys; sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_flood_map_national import USE, MODEL_KW      # noqa: E402

WL = ["wl_level", "wl_rise_6h", "wl_dist_km"]
SETS = {
    "기존 21개":        list(USE),
    "+상승폭":          list(USE) + ["wl_rise_6h"],
    "+수위 3개":        list(USE) + WL,
}


def capture(y, p, frac=0.05):
    k = max(int(round(len(p) * frac)), 1)
    return float(np.asarray(y)[np.argsort(-p)[:k]].sum()) / max(float(np.sum(y)), 1.0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_wl.csv")
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--out", type=Path, default=ROOT / "outputs/flooded-building-register/waterlevel.json")
    a = ap.parse_args()

    keep = sorted(set(list(USE) + WL + ["event", "flooded"]))
    d = pd.read_csv(a.table, usecols=keep, dtype={"event": str})
    # 비가 없는 채로 라벨만 있는 폭풍은 지도에서도 뺀다. 같은 기준을 쓴다.
    sh = d[d.flooded == 1].groupby("event").rain_6h.apply(lambda s: (s < 1).mean())
    d = d[~d.event.isin(sh[sh >= 0.5].index)]
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    d = d.dropna(subset=list(USE))
    print(f"행 {len(d):,}  침수 {int(d.flooded.sum()):,}  폭풍 {d.event.nunique()}개")

    # 침수 칸 수가 고르게 퍼지도록 큰 폭풍부터 번갈아 담는다
    ev = d.groupby("event").flooded.sum().sort_values(ascending=False)
    fold = {}
    load = np.zeros(a.folds)
    for e, n in ev.items():
        i = int(np.argmin(load)); fold[e] = i; load[i] += n
    d["fold"] = d.event.map(fold)
    print("묶음별 침수 칸:", [int(x) for x in load], "\n")

    res = {}
    for name, use in SETS.items():
        aucs, aps, caps = [], [], []
        t0 = time.time()
        for f in range(a.folds):
            tr, te = d[d.fold != f], d[d.fold == f]
            if te.flooded.sum() == 0:
                continue
            pos = max(int(tr.flooded.sum()), 1)
            m = XGBClassifier(eval_metric="logloss", n_jobs=a.jobs,
                              scale_pos_weight=(len(tr) - pos) / pos, **MODEL_KW)
            m.fit(tr[use], tr.flooded)
            p = m.predict_proba(te[use])[:, 1]
            aucs.append(roc_auc_score(te.flooded, p))
            aps.append(average_precision_score(te.flooded, p))
            caps.append(capture(te.flooded, p))
            print(f"    {name} 묶음 {f+1}/{a.folds}  AUC {aucs[-1]:.4f}  "
                  f"상위5% {caps[-1]*100:.1f}%  ({(time.time()-t0)/60:.0f}분)", flush=True)
        res[name] = {"auc": float(np.mean(aucs)), "pr_auc": float(np.mean(aps)),
                     "top5": float(np.mean(caps)) * 100,
                     "per_fold_auc": [round(float(x), 4) for x in aucs],
                     "per_fold_top5": [round(float(x) * 100, 2) for x in caps]}
        print(f"  {name:12} AUC {res[name]['auc']:.4f}  PR-AUC {res[name]['pr_auc']:.4f}  "
              f"상위5% {res[name]['top5']:5.1f}%\n", flush=True)

    b = res["기존 21개"]
    print("=== 기존 대비 ===")
    for name in list(SETS)[1:]:
        r = res[name]
        w = sum(1 for x, y in zip(b["per_fold_top5"], r["per_fold_top5"]) if y > x)
        print(f"  {name:12} AUC {r['auc']-b['auc']:+.4f}  "
              f"상위5% {r['top5']-b['top5']:+.1f}p  이긴 묶음 {w}/{len(r['per_fold_top5'])}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
