#!/usr/bin/env python3
"""걸름망을 고친 표가 실제로 나은가. 시험지를 같게 놓고 잰다.

고친 표(dry)에는 "잠긴 적 있는 자리가 비가 적어 이번엔 무사했다"는 칸이 새로
들어 있다. 그 칸들은 강수가 하는 일을 보여주는 유일한 대비인데, 옛 표에는 한
건도 없었다.

두 표는 행 수가 다르므로 그냥 점수를 비교하면 안 된다. 되살아난 칸은 전부
비가 적게 온 칸이라 맞히기 쉽고, 시험지에 섞으면 점수가 저절로 오른다.

그래서 시험은 \033[1m양쪽 표에 공통으로 있는 조건\033[0m 위에서만 한다 -- 6 시간 강수가
10 mm 이상인 칸. 되살아난 칸은 정의상 10 mm 미만이므로 시험지에서 빠지고
학습에만 들어간다. 이래야 "새 자료로 배운 것이 실제로 도움이 되는가"를 묻는
질문이 된다.
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


def prep(path, cols):
    d = pd.read_csv(path, usecols=cols, dtype={"event": str})
    sh = d[d.flooded == 1].groupby("event").rain_6h.apply(lambda s: (s < 1).mean())
    d = d[~d.event.isin(sh[sh >= 0.5].index)]
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    return d.dropna(subset=list(USE))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_all_full.csv")
    ap.add_argument("--new", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_dry.csv")
    ap.add_argument("--test-rain-min", type=float, default=10.0)
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--jobs", type=int, default=9)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "outputs/flooded-building-register/dry_vs_all.json")
    a = ap.parse_args()

    cols = sorted({*USE, "event", "flooded"})
    tabs = {"옛 표": prep(a.old, cols), "고친 표": prep(a.new, cols)}
    for k, v in tabs.items():
        print(f"{k}: {len(v):,}행  침수 {int(v.flooded.sum()):,}  폭풍 {v.event.nunique()}개")

    # 묶음은 두 표에 같은 방식으로 매긴다 (사건 이름 기준이라 동일해진다)
    base = tabs["옛 표"]
    ev = base.groupby("event").flooded.sum().sort_values(ascending=False)
    fold, load = {}, np.zeros(a.folds)
    for e, n in ev.items():
        i = int(np.argmin(load)); fold[e] = i; load[i] += n
    for v in tabs.values():
        v["fold"] = v.event.map(fold)

    # 시험지는 옛 표에서만 가져온다. 양쪽에 공통이고 비가 온 칸.
    res = {k: [] for k in tabs}
    t0 = time.time()
    for f in range(a.folds):
        te = base[(base.fold == f) & (base.rain_6h >= a.test_rain_min)]
        if te.flooded.sum() == 0:
            continue
        for name, tab in tabs.items():
            tr = tab[(tab.fold != f) & tab.fold.notna()]
            pos = max(int(tr.flooded.sum()), 1)
            m = XGBClassifier(eval_metric="logloss", n_jobs=a.jobs,
                              scale_pos_weight=(len(tr) - pos) / pos, **MODEL_KW)
            m.fit(tr[USE], tr.flooded)
            p = m.predict_proba(te[USE])[:, 1]
            res[name].append({"auc": float(roc_auc_score(te.flooded, p)),
                              "top5": float(capture(te.flooded, p)) * 100,
                              "train_rows": int(len(tr))})
            r = res[name][-1]
            print(f"  묶음 {f+1} {name:<8} 학습 {r['train_rows']:>10,}행  "
                  f"AUC {r['auc']:.4f}  상위5% {r['top5']:5.1f}%  "
                  f"(시험 {len(te):,}칸, 침수 {int(te.flooded.sum()):,})  "
                  f"({(time.time()-t0)/60:.0f}분)", flush=True)

    print(f"\n=== 같은 시험지 (비 {a.test_rain_min:.0f}mm 이상) ===")
    for k, v in res.items():
        print(f"  {k:<8} AUC {np.mean([x['auc'] for x in v]):.4f}   "
              f"상위5% {np.mean([x['top5'] for x in v]):5.1f}%")
    d5 = np.array([x["top5"] for x in res["고친 표"]]) - \
         np.array([x["top5"] for x in res["옛 표"]])
    se = d5.std(ddof=1) / np.sqrt(len(d5))
    v = "채택" if d5.mean() > 2*se else ("기각" if d5.mean() < -2*se else "판정불가")
    print(f"\n  \033[1m걸름망 수정 효과: 상위5% {d5.mean():+.2f}p ± {se:.2f}\033[0m"
          f"   이긴 묶음 {int((d5>0).sum())}/{len(d5)}  -> {v}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
