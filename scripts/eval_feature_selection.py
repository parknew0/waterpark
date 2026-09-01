#!/usr/bin/env python3
"""변수를 줄이면 나아지는가. 그리고 차원축소가 이 문제에 맞는가.

행이 2 천만이라 차원의 저주와는 거리가 멀어 보인다. 그러나 \033[1m독립된 단위는 행이
아니라 폭풍\033[0m 이다. 같은 폭풍의 칸들은 같은 비 안에 있고 서로 붙어 있다. 88 개
폭풍에 21 개 변수라면 보이는 것만큼 넉넉하지 않다.

상관행렬을 보니 겹침이 뚜렷하다. rel_500m 과 rel_1000m 이 0.971, rel_200m 과
rel_500m 이 0.946 -- 주변 대비 높이를 네 번 재고 있다.

여섯 가지를 같은 시험지에서 견준다.

  기존 21개
  겹침 제거      rel_1000m·rel_200m·built_count 를 뺀 18개
  중요도 상위 k개  한 번 학습해 이득(gain)으로 순위를 매기고 위에서 자른다
  주성분 12개    PCA. 트리는 축에 나란한 칸막이로 자르므로 회전이 해가 될 것으로
                보지만, 그것도 재본 적이 없으니 넣는다
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_flood_map_national import USE, MODEL_KW      # noqa: E402

REDUNDANT = ["rel_1000m", "rel_200m", "built_count"]


def capture(y, p, frac=0.05):
    k = max(int(round(len(p) * frac)), 1)
    return float(np.asarray(y)[np.argsort(-p)[:k]].sum()) / max(float(np.sum(y)), 1.0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_88.csv")
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--sample", type=float, default=0.35)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "outputs/flooded-building-register/feature_selection.json")
    a = ap.parse_args()

    cols = sorted({*USE, "event", "flooded"})
    dt = {c: "float32" for c in cols if c not in ("event", "flooded")}
    dt.update({"event": str, "flooded": "int8"})
    d = pd.read_csv(a.table, usecols=cols, dtype=dt)
    if a.sample < 1.0:
        d = d.sample(frac=a.sample, random_state=0)
    sh = d[d.flooded == 1].groupby("event").rain_6h.apply(lambda s: (s < 1).mean())
    d = d[~d.event.isin(sh[sh >= 0.5].index)]
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    d = d.dropna(subset=list(USE))
    ev = d.groupby("event").flooded.sum().sort_values(ascending=False)
    fold, load = {}, np.zeros(a.folds)
    for e, n in ev.items():
        i = int(np.argmin(load)); fold[e] = i; load[i] += n
    d["fold"] = d.event.map(fold)
    print(f"행 {len(d):,}  침수 {int(d.flooded.sum()):,}  폭풍 {d.event.nunique()}개\n")

    # 중요도 순위는 시험지를 보지 않고 첫 묶음의 학습 부분에서만 뽑는다
    tr0 = d[d.fold != 0]
    pos = max(int(tr0.flooded.sum()), 1)
    m0 = XGBClassifier(eval_metric="logloss", n_jobs=a.jobs,
                       scale_pos_weight=(len(tr0) - pos) / pos, **MODEL_KW)
    m0.fit(tr0[USE], tr0.flooded)
    imp = pd.Series(m0.get_booster().get_score(importance_type="gain"))
    rank = [c for c in imp.sort_values(ascending=False).index if c in USE]
    rank += [c for c in USE if c not in rank]
    print("이득 순위:", ", ".join(rank[:8]), "...\n")

    sets = {"기존 21개": list(USE),
            "겹침 제거 18개": [c for c in USE if c not in REDUNDANT],
            "중요도 상위 12개": rank[:12],
            "중요도 상위 8개": rank[:8],
            "중요도 상위 4개": rank[:4],
            "주성분 12개": None}

    res = {k: [] for k in sets}
    t0 = time.time()
    for f in range(a.folds):
        tr, te = d[d.fold != f], d[d.fold == f]
        if te.flooded.sum() == 0:
            continue
        pos = max(int(tr.flooded.sum()), 1)
        w = (len(tr) - pos) / pos
        for name, use in sets.items():
            if use is None:
                sc = StandardScaler().fit(tr[USE])
                pca = PCA(n_components=12, random_state=0).fit(sc.transform(tr[USE]))
                Xtr, Xte = pca.transform(sc.transform(tr[USE])), pca.transform(sc.transform(te[USE]))
            else:
                Xtr, Xte = tr[use], te[use]
            m = XGBClassifier(eval_metric="logloss", n_jobs=a.jobs,
                              scale_pos_weight=w, **MODEL_KW)
            m.fit(Xtr, tr.flooded)
            p = m.predict_proba(Xte)[:, 1]
            res[name].append({"auc": float(roc_auc_score(te.flooded, p)),
                              "top5": float(capture(te.flooded, p)) * 100})
        print(f"  묶음 {f+1}/{a.folds}  " +
              "  ".join(f"{k.split()[0]} {res[k][-1]['top5']:.1f}" for k in sets) +
              f"  ({(time.time()-t0)/60:.0f}분)", flush=True)

    print("\n=== 결과 ===")
    for k, v in res.items():
        print(f"  {k:<16} AUC {np.mean([x['auc'] for x in v]):.4f}   "
              f"상위5% {np.mean([x['top5'] for x in v]):5.1f}%")
    base = np.array([x["top5"] for x in res["기존 21개"]])
    print("\n=== 기존 21개 대비 (같은 묶음끼리) ===")
    for k in list(sets)[1:]:
        dd = np.array([x["top5"] for x in res[k]]) - base
        se = dd.std(ddof=1) / np.sqrt(len(dd))
        v = "낫다" if dd.mean() > 2*se else ("못하다" if dd.mean() < -2*se else "판정불가")
        print(f"  {k:<16} {dd.mean():+.2f}p ± {se:.2f}   이긴 묶음 {int((dd>0).sum())}/{len(dd)}  -> {v}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"결과": res, "이득순위": rank}, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
