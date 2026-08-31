#!/usr/bin/env python3
"""도로 침수 위험지점으로 채점한다. 우리 라벨과 출처가 다른 세 번째 시험지.

교통안전정보(DSSP-IF-10019)에 "상습침수지역", "집중호우 발생시 도로침수 우려지역"
으로 등록된 지점이 657 곳 있다. 좌표가 100% 붙어 있고, 우리 침수 라벨 칸과
겹치는 것은 4.3% 뿐이다. 침수흔적 조사가 아니라 교통안전 점검에서 나온 자료라
우리 라벨의 편향을 물려받지 않는다.

기사 채점은 세 번 다 실패했는데, 실패의 원인이 눈금이었다. 시군구는 384 km2,
읍면동은 4 km2 였고 우리 모델이 답하는 것은 30 m 칸이다. 이 자료는 점이므로
처음으로 우리 눈금에서 채점할 수 있다.

읍면동 채점에서 배운 것을 그대로 넣는다. 그때 "넓이만" 이 강수보다 잘 맞혔고,
시험이 침수가 아니라 넓이를 재고 있었다. 여기서는 짝을 지어 그 함정을 없앤다 --
위험지점마다 \033[1m같은 시군구 안에서\033[0m 대조점을 뽑아, 둘 중 어느 쪽을 높게 매기는지만
본다. 지역이 같으므로 지역 때문에 생기는 차이는 상쇄된다.

기준선도 나란히 놓는다. 우리 21 개 열이 표고 하나보다 나은지가 이 채점의 질문이다.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
G30 = ROOT / "data/interim/grid30"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_flood_map_national import USE, MODEL_KW, RATIO_1H_6H, PLATEAU_MM  # noqa: E402

STATIC = [c for c in USE if c not in ("rain_1h", "rain_6h")]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_88.csv")
    ap.add_argument("--points", type=Path,
                    default=ROOT / "data/interim/flood-labels/road_flood_points.csv")
    ap.add_argument("--controls", type=int, default=40, help="위험지점 하나당 대조점 수")
    ap.add_argument("--rain", type=float, default=40.0)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "outputs/flooded-building-register/road_eval.json")
    a = ap.parse_args()

    g = json.loads((G30 / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    R, C = g["rows"], g["cols"]
    sgg = np.load(G30 / "sgg_id.npy", mmap_mode="r")
    el = np.load(G30 / "elevation.npy", mmap_mode="r")

    pts = pd.read_csv(a.points)
    # 우리 라벨과 겹치는 점은 뺀다. 겹치면 독립된 시험이 아니다.
    z = np.load(ROOT / "data/interim/flood-labels/flood_cells30_plus.npz")
    lab = set()
    for k in z.files:
        if k.startswith("e"):
            lab.update(z[k].tolist())
    keep = ~pts.apply(lambda r: int(r.row) * C + int(r.col) in lab, axis=1)
    pts = pts[keep].reset_index(drop=True)
    pts["sgg"] = sgg[pts.row.to_numpy(), pts.col.to_numpy()]
    pts = pts[pts.sgg > 0]
    print(f"위험지점 {len(pts):,}곳 (우리 라벨과 겹치는 것 제외), 시군구 {pts.sgg.nunique()}개")

    # 같은 시군구 안에서 대조점을 뽑는다
    step = 3
    sub = np.asarray(sgg[::step, ::step])
    sube = np.asarray(el[::step, ::step], dtype="float32")
    ok = (sub > 0) & np.isfinite(sube) & (sube > 0)
    ids = sub[ok]
    rr, cc = (x * step for x in np.nonzero(ok))
    order = np.argsort(ids, kind="stable")
    ids, rr, cc = ids[order], rr[order], cc[order]
    uniq, starts = np.unique(ids, return_index=True)
    edges = dict(zip(uniq.tolist(), zip(starts.tolist(), list(starts[1:]) + [len(ids)])))
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
    print(f"대조점 {len(crow):,}곳 (위험지점당 최대 {a.controls}곳, 같은 시군구 안)")

    allr = np.r_[pts.row.to_numpy(), crow]
    allc = np.r_[pts.col.to_numpy(), ccol]
    grp = np.r_[np.arange(len(pts)), cgrp]
    y = np.r_[np.ones(len(pts), dtype=int), np.zeros(len(crow), dtype=int)]

    print("학습 표 읽는 중", flush=True)
    d = pd.read_csv(a.table, usecols=sorted({*USE, "event", "flooded"}), dtype={"event": str})
    sh = d[d.flooded == 1].groupby("event").rain_6h.apply(lambda s: (s < 1).mean())
    d = d[~d.event.isin(sh[sh >= 0.5].index)]
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    d = d.dropna(subset=list(USE))
    pos = max(int(d.flooded.sum()), 1)
    w = (len(d) - pos) / pos
    m = XGBClassifier(eval_metric="logloss", n_jobs=9, scale_pos_weight=w, **MODEL_KW)
    m.fit(d[USE], d.flooded)
    med = {c: float(d[c].median()) for c in USE}
    del d
    print("학습 완료", flush=True)

    cols = {}
    for n in STATIC:
        v = np.asarray(np.load(G30 / f"{n}.npy", mmap_mode="r")[allr, allc], dtype="float32")
        cols[n] = np.where(np.isfinite(v), v, med[n])
    X = np.empty((len(allr), len(USE)), dtype="float32")
    for j, n in enumerate(USE):
        X[:, j] = (min(a.rain, PLATEAU_MM) if n == "rain_6h" else
                   min(a.rain, PLATEAU_MM) * RATIO_1H_6H if n == "rain_1h" else cols[n])
    p = m.predict_proba(X)[:, 1]
    odds = p / np.maximum(1 - p, 1e-9) / w
    score = odds / (1 + odds)

    df = pd.DataFrame({"y": y, "grp": grp, "우리 모델": score})
    for n, lab_ in (("elevation", "표고만 (낮을수록)"), ("rel_500m", "주변대비 높이만"),
                    ("dist_stream", "하천거리만"), ("sink_depth", "우묵한 정도만"),
                    ("impervious", "불투수율만")):
        df[lab_] = -cols[n] if n in ("elevation", "rel_500m", "dist_stream") else cols[n]

    print(f"\n\033[1m전국을 한 통에 놓고 (지역 차이가 섞인다)\033[0m")
    out = {}
    for c in df.columns[2:]:
        auc = roc_auc_score(df.y, df[c])
        out.setdefault("전국", {})[c] = float(auc)
        print(f"  {c:<18} AUC {auc:.4f}")

    # 짝지어 비교: 같은 시군구 안에서 위험지점이 대조점보다 높은가
    print(f"\n\033[1m같은 시군구 안에서 짝지어 (지역 차이를 없앤다)\033[0m")
    for c in df.columns[2:]:
        wins = []
        for gid, sub2 in df.groupby("grp"):
            t = sub2[sub2.y == 1][c]
            ctl = sub2[sub2.y == 0][c]
            if len(t) == 0 or len(ctl) == 0:
                continue
            wins.append(float((ctl < t.iat[0]).mean()))
        v = float(np.mean(wins))
        se = float(np.std(wins, ddof=1) / np.sqrt(len(wins)))
        out.setdefault("짝지음", {})[c] = {"승률": v, "오차": se, "짝": len(wins)}
        print(f"  {c:<18} 대조점보다 높게 매긴 비율 {v*100:5.1f}% ± {se*100:.1f}")
    print(f"\n  (50% 는 동전 던지기. 짝 {len(wins):,}개)")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
