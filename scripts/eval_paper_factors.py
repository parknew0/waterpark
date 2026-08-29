#!/usr/bin/env python3
"""논문이 표준으로 꼽는 인자들이 실제로 도움이 되는가.

국제 리뷰는 도시 침수 인자를 기후·지형·토지이용·배수 네 갈래로 나누고,
국내 연구는 한계강우량을 정하는 유역 인자로 관거밀도·빗물받이 밀도·유역경사·
불투수율·펌프장 배제능력 다섯을 꼽는다. 우리에게는 배수 갈래가 통째로
없었고, 다섯 중 둘만 있었다.

이번에 그 빈칸을 메웠다. 다만 이 세션에서 "교과서에 있으니 도움될 것"이라는
추론이 다섯 번 빗나갔으므로, 논문에 나온다는 사실은 채택 근거가 아니다.
갈래별로 넣고 빼며 사건을 하나씩 홀드아웃해 확인한다.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
BASE = ["elevation", "rel_200m", "rel_500m", "rel_1000m", "slope_deg",
        "built_ratio", "built_count", "impervious", "water", "rain_1h", "rain_6h"]
HYDRO = ["flow_acc", "sink_depth"]
SHAPE = ["curvature", "tpi_200m", "tpi_1000m"]
DRAIN = ["drainage_density", "dist_stream"]
MANMADE = ["dist_pump", "pump_capacity", "sewer_density"]
FR = (0.01, 0.05, 0.10)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_v4.csv")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()

    cols = sorted(set(BASE + HYDRO + SHAPE + DRAIN + MANMADE))
    d = pd.read_csv(a.table)
    d["event"] = d.event.astype(str)
    share = d[d.flooded == 1].groupby("event").rain_6h.apply(lambda s: (s < 1).mean())
    d = d[~d.event.isin(share[share >= 0.5].index)]
    # 관거밀도는 시군구 경계 밖이 결측이다. 버리면 표본이 반토막 나므로
    # 중앙값으로 채우고, 채웠다는 사실 자체를 따로 알리지는 않는다.
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    d = d.dropna(subset=cols)
    ev = [e for e, n in d.groupby("event").flooded.sum().items() if n >= 20]
    print(f"칸 {len(d):,}  침수 {int(d.flooded.sum()):,} "
          f"({d.flooded.mean()*100:.3f}%)  사건 {len(ev)}\n")

    sets = {
        "① 기존": BASE,
        "② +수문 (집수·웅덩이)": BASE + HYDRO,
        "③ +지형형태 (곡률·TPI)": BASE + SHAPE,
        "④ +배수 (하천밀도·거리)": BASE + DRAIN,
        "⑤ +인공배수 (펌프·관거)": BASE + MANMADE,
        "⑥ 전부": BASE + HYDRO + SHAPE + DRAIN + MANMADE,
    }
    res = {}
    for name, use in sets.items():
        A, P, cap = [], [], {f: [] for f in FR}
        for e in ev:
            tr, te = d[d.event != e], d[d.event == e]
            pos = max(int(tr.flooded.sum()), 1)
            m = XGBClassifier(n_estimators=400, max_depth=5, learning_rate=0.05,
                              subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
                              reg_lambda=2.0, eval_metric="logloss", n_jobs=8,
                              scale_pos_weight=(len(tr) - pos) / pos)
            m.fit(tr[use], tr.flooded)
            p = m.predict_proba(te[use])[:, 1]
            A.append(roc_auc_score(te.flooded, p))
            P.append(average_precision_score(te.flooded, p))
            o = np.argsort(-p); y = te.flooded.values
            for f in FR:
                k = max(int(round(len(p) * f)), 1)
                cap[f].append(y[o[:k]].sum() / max(y.sum(), 1))
        res[name] = {"auc": float(np.mean(A)), "pr_auc": float(np.mean(P)),
                     **{f"top{int(f*100)}": float(np.mean(cap[f])) for f in FR}}
        r = res[name]
        print(f"  {name:24} AUC {r['auc']:.4f}  PR {r['pr_auc']:.4f}  "
              f"상위1% {r['top1']*100:5.1f}%  5% {r['top5']*100:5.1f}%  "
              f"10% {r['top10']*100:5.1f}%", flush=True)

    b = res["① 기존"]
    print("\n=== 기존 대비 ===")
    for name in list(sets)[1:]:
        r = res[name]
        print(f"  {name:24} AUC {r['auc']-b['auc']:+.4f}   "
              f"상위5% {(r['top5']-b['top5'])*100:+5.1f}p   "
              f"상위10% {(r['top10']-b['top10'])*100:+5.1f}p")
    if a.out:
        a.out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
