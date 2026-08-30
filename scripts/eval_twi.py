#!/usr/bin/env python3
"""습윤지수가 이제는 제 값을 하는가.

TWI 는 예전 실험에서 떨어졌다. 그런데 그때 쓰인 집수면적은 웅덩이를 메우지
않은 채 계산한 값이라 물길이 오목한 데마다 끊겨 있었다. 중앙값이 2 칸,
최대가 2,481 칸이었고 제대로 계산하면 290만 칸이다. 100만 배 틀린 값을 재고서
"도움이 안 된다"고 적은 셈이다.

집수면적 자체는 고친 뒤 21개 안에 들어갔지만, 거기서 파생되는 TWI 와 SPI 는
다시 재본 적이 없다. 새 자료가 필요 없고 표에 이미 있는 두 열로 계산된다.

  TWI = ln(단위폭당 집수면적 / tan(경사))   물이 모이고 잘 안 빠지는 정도
  SPI = ln(단위폭당 집수면적 * tan(경사))   흐르는 물이 가진 힘

경사가 0 이면 tan 도 0 이라 나눌 수 없다. 평지는 30 m 격자에서 흔하므로
최소 경사를 두어 막는다. 이 하한을 어디에 두느냐가 평지의 TWI 순위를 정한다.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_flood_map_national import USE, MODEL_KW      # noqa: E402

CELL = 30.0
MIN_SLOPE_DEG = 0.05      # 30 m 격자에서 이보다 평평한 경사는 측정 잡음이다


def capture(y, p, frac=0.05):
    k = max(int(round(len(p) * frac)), 1)
    return float(np.asarray(y)[np.argsort(-p)[:k]].sum()) / max(float(np.sum(y)), 1.0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_poly.csv")
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "outputs/flooded-building-register/twi.json")
    a = ap.parse_args()

    d = pd.read_csv(a.table, usecols=sorted(set(list(USE) + ["event", "flooded"])),
                    dtype={"event": str})
    sh = d[d.flooded == 1].groupby("event").rain_6h.apply(lambda s: (s < 1).mean())
    d = d[~d.event.isin(sh[sh >= 0.5].index)]
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    d = d.dropna(subset=list(USE))

    # 단위폭당 집수면적: 칸 수 x 칸 넓이 / 칸 한 변
    area = np.maximum(d.flow_acc.to_numpy(), 1.0) * CELL
    tanb = np.tan(np.radians(np.maximum(d.slope_deg.to_numpy(), MIN_SLOPE_DEG)))
    d["twi"] = np.log(area / tanb)
    d["spi"] = np.log(area * tanb)
    print(f"행 {len(d):,}  침수 {int(d.flooded.sum()):,}  폭풍 {d.event.nunique()}개")
    print(f"TWI 중앙값 {d.twi.median():.2f}  "
          f"침수칸 {d.loc[d.flooded==1,'twi'].median():.2f}  "
          f"안잠김 {d.loc[d.flooded==0,'twi'].median():.2f}")
    print(f"SPI 중앙값 {d.spi.median():.2f}  "
          f"침수칸 {d.loc[d.flooded==1,'spi'].median():.2f}  "
          f"안잠김 {d.loc[d.flooded==0,'spi'].median():.2f}")

    sets = {"기존 21개": list(USE),
            "+TWI": list(USE) + ["twi"],
            "+TWI·SPI": list(USE) + ["twi", "spi"]}

    # 수위 실험과 같은 방식으로 묶어 결과를 나란히 놓을 수 있게 한다
    ev = d.groupby("event").flooded.sum().sort_values(ascending=False)
    fold, load = {}, np.zeros(a.folds)
    for e, n in ev.items():
        i = int(np.argmin(load)); fold[e] = i; load[i] += n
    d["fold"] = d.event.map(fold)
    print("묶음별 침수 칸:", [int(x) for x in load], "\n")

    res = {}
    for name, use in sets.items():
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
        print(f"  {name:12} AUC {res[name]['auc']:.4f}  상위5% {res[name]['top5']:5.1f}%\n",
              flush=True)

    b = res["기존 21개"]
    print("=== 기존 대비 (같은 묶음끼리 짝지어 비교) ===")
    for name in list(sets)[1:]:
        r = res[name]
        da = np.array(r["per_fold_auc"]) - np.array(b["per_fold_auc"])
        dt = np.array(r["per_fold_top5"]) - np.array(b["per_fold_top5"])
        sa = da.std(ddof=1) / np.sqrt(len(da))
        stt = dt.std(ddof=1) / np.sqrt(len(dt))
        print(f"  {name:10} AUC {da.mean():+.4f} ± {sa:.4f}   "
              f"상위5% {dt.mean():+.1f}p ± {stt:.1f}   이긴 묶음 {int((dt>0).sum())}/{len(dt)}")
    print("\n  오차의 2배보다 작은 차이는 우연과 구분할 수 없다.")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  -> {a.out}")


if __name__ == "__main__":
    main()
