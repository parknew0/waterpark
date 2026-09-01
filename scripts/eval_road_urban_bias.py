#!/usr/bin/env python3
"""손질한 설정이 [1m바깥에서도[0m 나은가. 도로 침수 위험지점으로 짝지어 잰다.

설정을 손질해 우리 라벨에서 +1.94p 를 얻었다. 그런데 우리 라벨은 조사가 이뤄진
곳에서만 온다. 그 정답지에 맞춰 손잡이를 돌린 것이 [1m바깥에서도[0m 나은지, 아니면
우리 정답지에만 더 맞춘 것인지는 다른 자료로 봐야 안다.

도로 침수 위험지점 657 곳은 교통안전 점검에서 나왔고 우리 라벨과 4.3% 만 겹친다.
옛 설정은 여기서 75.7%, 표고 하나가 78.4% 였다. 격차가 줄면 손질이 진짜였던 것이고,
그대로면 우리 정답지에만 맞춘 것이다.

도로 채점에서 우리 21 개 열(75.7%)이 표고 하나(78.4%)에게 졌다. 그리고 불투수율
하나만 쓰면 41.7% -- 50% 아래, 즉 \033[1m거꾸로\033[0m 작동한다. 위험지점들이 대조점보다
덜 도시적이라는 뜻이다.

우리 모델은 시가지·불투수율을 위험 신호로 쓴다. 침수흔적 조사가 도시에 몰려
있어서 그렇게 배웠다. 그것이 이 자료에서 우리를 끌어내리는지 직접 잰다.

같은 626 짝 위에서 두 모델을 나란히 학습하고, 짝마다 차이를 내어 오차까지 낸다.
조건이 하나만 다르므로 차이는 도시 열 셋에서만 온다.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
G30 = ROOT / "data/interim/grid30"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_flood_map_national import USE, MODEL_KW, RATIO_1H_6H, PLATEAU_MM  # noqa: E402

URBAN = ["built_ratio", "built_count", "impervious"]
BEST = ROOT / "outputs/flooded-building-register/best_model_kw.json"


def tuned_kw():
    """손질한 설정이 있으면 쓴다. 우리 라벨에서 +1.94p 였던 것이 바깥에서도
    나은지가 이 시험의 요점이다."""
    import json
    if BEST.exists():
        j = json.loads(BEST.read_text(encoding="utf-8"))
        print(f"손질한 설정을 쓴다: {j['이름']} (우리 라벨 상위5% {j['상위5%']:.1f}%)")
        return j["kw"]
    return dict(MODEL_KW)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_88.csv")
    ap.add_argument("--points", type=Path,
                    default=ROOT / "data/interim/flood-labels/road_flood_points.csv")
    ap.add_argument("--controls", type=int, default=40)
    ap.add_argument("--rain", type=float, default=40.0)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "outputs/flooded-building-register/road_tuned.json")
    a = ap.parse_args()

    g = json.loads((G30 / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    C = g["cols"]
    sgg = np.load(G30 / "sgg_id.npy", mmap_mode="r")
    el = np.load(G30 / "elevation.npy", mmap_mode="r")

    pts = pd.read_csv(a.points)
    z = np.load(ROOT / "data/interim/flood-labels/flood_cells30_plus.npz")
    lab = set()
    for k in z.files:
        if k.startswith("e"):
            lab.update(z[k].tolist())
    pts = pts[~pts.apply(lambda r: int(r.row) * C + int(r.col) in lab, axis=1)].reset_index(drop=True)
    pts["sgg"] = sgg[pts.row.to_numpy(), pts.col.to_numpy()]
    pts = pts[pts.sgg > 0].reset_index(drop=True)

    step = 3
    sub = np.asarray(sgg[::step, ::step]); sube = np.asarray(el[::step, ::step], dtype="float32")
    ok = (sub > 0) & np.isfinite(sube) & (sube > 0)
    ids = sub[ok]; rr, cc = (x * step for x in np.nonzero(ok))
    o = np.argsort(ids, kind="stable"); ids, rr, cc = ids[o], rr[o], cc[o]
    uq, st = np.unique(ids, return_index=True)
    edges = dict(zip(uq.tolist(), zip(st.tolist(), list(st[1:]) + [len(ids)])))
    rng = np.random.default_rng(0)
    crow, ccol, cgrp = [], [], []
    for i, s in enumerate(pts.sgg.to_numpy()):
        if int(s) not in edges:
            continue
        s0, s1 = edges[int(s)]
        n = min(a.controls, s1 - s0)
        sel = rng.choice(np.arange(s0, s1), n, replace=False)
        crow.append(rr[sel]); ccol.append(cc[sel]); cgrp.append(np.full(n, i))
    crow = np.concatenate(crow); ccol = np.concatenate(ccol); cgrp = np.concatenate(cgrp)
    allr = np.r_[pts.row.to_numpy(), crow]; allc = np.r_[pts.col.to_numpy(), ccol]
    grp = np.r_[np.arange(len(pts)), cgrp]
    y = np.r_[np.ones(len(pts), int), np.zeros(len(crow), int)]
    print(f"위험지점 {len(pts):,}곳, 대조점 {len(crow):,}곳", flush=True)

    print("학습 표 읽는 중", flush=True)
    d = pd.read_csv(a.table, usecols=sorted({*USE, "event", "flooded"}), dtype={"event": str})
    sh = d[d.flooded == 1].groupby("event").rain_6h.apply(lambda s: (s < 1).mean())
    d = d[~d.event.isin(sh[sh >= 0.5].index)]
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    d = d.dropna(subset=list(USE))
    med = {c: float(d[c].median()) for c in USE}

    layers = {}
    for n in [c for c in USE if c not in ("rain_1h", "rain_6h")]:
        v = np.asarray(np.load(G30 / f"{n}.npy", mmap_mode="r")[allr, allc], dtype="float32")
        layers[n] = np.where(np.isfinite(v), v, med[n])

    res = {}
    tuned = tuned_kw()
    sets = {"옛 설정": (list(USE), dict(MODEL_KW)),
            "손질한 설정": (list(USE), tuned)}
    scores = {}
    for name, (use, kw) in sets.items():
        pos = max(int(d.flooded.sum()), 1)
        w = (len(d) - pos) / pos
        m = XGBClassifier(eval_metric="logloss", n_jobs=9, scale_pos_weight=w, **kw)
        m.fit(d[use], d.flooded)
        X = np.empty((len(allr), len(use)), dtype="float32")
        for j, n in enumerate(use):
            X[:, j] = (min(a.rain, PLATEAU_MM) if n == "rain_6h" else
                       min(a.rain, PLATEAU_MM) * RATIO_1H_6H if n == "rain_1h" else layers[n])
        p = m.predict_proba(X)[:, 1]
        odds = p / np.maximum(1 - p, 1e-9) / w
        scores[name] = odds / (1 + odds)
        print(f"  {name} 학습·채점 완료", flush=True)
    scores["표고만 (낮을수록)"] = -layers["elevation"]
    scores["주변대비 높이만"] = -layers["rel_500m"]

    df = pd.DataFrame({"y": y, "grp": grp, **scores})
    per = {}
    for c in scores:
        wins = []
        for _, s in df.groupby("grp"):
            t = s[s.y == 1][c]; ctl = s[s.y == 0][c]
            if len(t) and len(ctl):
                wins.append(float((ctl < t.iat[0]).mean()))
        per[c] = np.array(wins)
        print(f"  {c:<18} {per[c].mean()*100:5.1f}% ± {per[c].std(ddof=1)/np.sqrt(len(wins))*100:.1f}")

    print("\n\033[1m같은 짝끼리 빼면\033[0m")
    base = per["옛 설정"]
    for c in ("손질한 설정", "표고만 (낮을수록)", "주변대비 높이만"):
        dd = per[c] - base
        se = dd.std(ddof=1) / np.sqrt(len(dd))
        v = "낫다" if dd.mean() > 2*se else ("못하다" if dd.mean() < -2*se else "판정불가")
        print(f"  {c:<18} {dd.mean()*100:+.2f}p ± {se*100:.2f}   -> 기존보다 {v}")
        res[c] = {"차이": float(dd.mean()), "오차": float(se)}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"승률": {k: float(v.mean()) for k, v in per.items()},
                                 "짝지은차이": res}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
