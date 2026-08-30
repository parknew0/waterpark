#!/usr/bin/env python3
"""전국 침수 위험 지도. 강수 단계별로 한 장씩.

30 m 칸이 1억 9,600만 개라 강수 단계마다 전부 채점하면 한 시간이 넘는다.
행 블록으로 나눠 돌리고, 화면에 얹을 때는 8x8 블록의 최댓값을 남긴다.
평균을 내면 도로 한 칸짜리 위험이 주변 안전한 칸에 희석돼 사라지는데,
그런 자리를 보자고 30 m로 내려온 것이므로 최댓값이 맞다.

색은 확률이 아니라 그 강수에서의 순위다. 학습 자료의 실제 침수율은
10~80 mm 구간에서 0.94%, 0.98%, 0.89%로 거의 평평한데, 비가 늘 국지적이라
모델이 배운 것이 절대량이 아니라 '주변보다 여기가 더 왔다'는 대비이기
때문이다. 전국에 같은 비를 균일하게 뿌리는 이 그림에서는 그 대비가 없다.
"""
from __future__ import annotations
import argparse, json, time
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj
from PIL import Image
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
G30 = ROOT / "data/interim/grid30"
BASE = ["elevation", "rel_200m", "rel_500m", "rel_1000m", "slope_deg",
        "built_ratio", "built_count", "impervious", "water", "rain_1h", "rain_6h"]
EXTRA = ["flow_acc", "sink_depth", "curvature", "tpi_200m", "tpi_1000m",
         "drainage_density", "dist_stream", "dist_pump", "pump_capacity",
         "sewer_density"]
USE = BASE + EXTRA
# 실제 자료에서 1시간 강수는 6시간 강수의 0.20배다. 처음에 0.33을 넣었더니
# 150 mm 자리에 1시간 50 mm라는, 자료에 없는 조합을 준 셈이 되어 확률이
# 도리어 떨어졌다.
# 깊이와 나무 수는 5/400 -> 11/1200 이다. AUC는 0.864에서 0.859로 내려가지만
# 상위 5% 포착은 26.4%에서 32.2%로 오른다. 침수 칸이 0.4% 뿐이라 얕은 나무는
# 그 희귀한 조합을 넓은 구간 안에 뭉개버리고, 우리가 쓰는 것은 순위 전체가
# 아니라 맨 위이므로 그 거래가 남는다. 13/1500 에서는 다시 꺾인다.
MODEL_KW = dict(n_estimators=1200, max_depth=11, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
                reg_lambda=2.0)

RATIO_1H_6H = 0.20

# 40 mm 위에서 모델의 확률이 도리어 떨어진다. 물리가 아니라 라벨 탓이다:
# 우리 침수 라벨은 조사가 이뤄진 곳에서만 오므로, 폭우가 쏟아졌지만 아무도
# 조사하지 않은 칸이 "안 잠김"으로 들어가 있고 강수가 높을수록 그 비중이
# 커진다. 학습 자료의 실제 침수율도 30~80 mm 구간에서 0.98%, 0.89%로 평평하다.
#
# 그래서 확률을 그대로 쓰되 40 mm 이상은 40 mm 값을 유지한다. "더 위험해지지
# 않는다"는 보수적인 가정이며, 조사 편향이 만든 하락을 그대로 보여주는 것보다
# 정직하다.
PLATEAU_MM = 40.0


STATIC = [c for c in USE if c not in ("rain_1h", "rain_6h")]



def to_web_mercator(arr, meta, r0, c0, cell):
    """5179 격자를 웹 지도 좌표계로 다시 샘플링한다.

    Leaflet 의 imageOverlay 는 그림을 웹 메르카토르 사각형에 선형으로
    얹는다. 그런데 5179(UTM-K)의 사각형은 위경도에서 사다리꼴이라 -- 이
    격자는 서쪽 변만 8 km 어긋난다 -- 그대로 얹으면 산골짜기의 색이 능선
    위로 밀린다. 목적지 픽셀마다 원본 좌표를 되짚어 값을 가져온다.
    """
    import pyproj
    H, W = arr.shape
    fwd = pyproj.Transformer.from_crs("EPSG:5179", "EPSG:3857", always_xy=True)
    inv = pyproj.Transformer.from_crs("EPSG:3857", "EPSG:5179", always_xy=True)
    xs = meta["origin_x"] + (np.array([c0, c0 + W]) ) * cell
    ys = meta["origin_y_top"] - (np.array([r0, r0 + H])) * cell
    cx, cy = np.meshgrid([xs[0], xs[1]], [ys[0], ys[1]])
    mx, my = fwd.transform(cx.ravel(), cy.ravel())
    x0, x1, y0, y1 = mx.min(), mx.max(), my.min(), my.max()
    gx = np.linspace(x0, x1, W)
    gy = np.linspace(y1, y0, H)
    MX, MY = np.meshgrid(gx, gy)
    sx, sy = inv.transform(MX.ravel(), MY.ravel())
    cc = ((sx - meta["origin_x"]) / cell - c0).astype(np.int64)
    rr = ((meta["origin_y_top"] - sy) / cell - r0).astype(np.int64)
    ok = (rr >= 0) & (rr < H) & (cc >= 0) & (cc < W)
    out = np.zeros(H * W, dtype=arr.dtype)
    out[ok] = arr[rr[ok], cc[ok]]
    to84 = pyproj.Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    west, south = to84.transform(x0, y0)
    east, north = to84.transform(x1, y1)
    return out.reshape(H, W), [[south, west], [north, east]]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--levels", default="0,20,40,60,80,100,150")
    ap.add_argument("--shrink", type=int, default=8, help="화면용 축소 배수")
    ap.add_argument("--rows-per-block", type=int, default=1200)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_poly.csv")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs/flood-map-national")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    status = a.out / "status.json"

    def note(msg, frac=None):
        d = {"message": msg, "updated": time.strftime("%H:%M:%S")}
        if frac is not None:
            d["percent"] = round(frac * 100, 1)
        status.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        print(msg, flush=True)

    note("학습 표 읽는 중", 0.0)
    d = pd.read_csv(a.table)
    d["event"] = d.event.astype(str)
    sh = d[d.flooded == 1].groupby("event").rain_6h.apply(lambda s: (s < 1).mean())
    d = d[~d.event.isin(sh[sh >= 0.5].index)]
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    d = d.dropna(subset=USE)
    pos = max(int(d.flooded.sum()), 1)
    w = (len(d) - pos) / pos
    m = XGBClassifier(eval_metric="logloss", n_jobs=8,
                      scale_pos_weight=w, **MODEL_KW)
    m.fit(d[USE], d.flooded)
    med = {c: float(d[c].median()) for c in USE}
    del d
    note("학습 완료", 0.05)

    meta = json.loads((G30 / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    R, C, cell = meta["rows"], meta["cols"], meta["cell_m"]
    k = a.shrink
    OH, OW = R // k, C // k
    layers = {n: np.load(G30 / f"{n}.npy", mmap_mode="r") for n in STATIC}
    levels = [float(v) for v in a.levels.split(",")]
    small = {lv: np.zeros((OH, OW), dtype="float32") for lv in levels}

    blocks = list(range(0, OH * k, a.rows_per_block))
    for bi, r0 in enumerate(blocks):
        r1 = min(r0 + a.rows_per_block, OH * k)
        cols = {}
        for n in STATIC:
            v = np.asarray(layers[n][r0:r1, :OW * k], dtype="float32")
            cols[n] = np.where(np.isfinite(v), v, med[n]).ravel()
        el = np.asarray(layers["elevation"][r0:r1, :OW * k], dtype="float32")
        land = (np.isfinite(el) & (el > 0)).ravel()
        h = r1 - r0
        for lv in levels:
            eff = min(lv, PLATEAU_MM)
            cols["rain_6h"] = np.full(h * OW * k, eff, dtype="float32")
            cols["rain_1h"] = np.full(h * OW * k, eff * RATIO_1H_6H, dtype="float32")
            X = np.column_stack([cols[c] for c in USE])
            p = m.predict_proba(X)[:, 1]
            odds = p / np.maximum(1 - p, 1e-9) / w      # 확률로 되돌린다
            p = np.where(land, odds / (1 + odds), 0.0).reshape(h, OW * k)
            # 8x8 블록의 최댓값: 평균 내면 도로 한 칸짜리 위험이 사라진다
            small[lv][r0 // k:r1 // k] = p.reshape(h // k, k, OW, k).max(axis=(1, 3))
        note(f"블록 {bi+1}/{len(blocks)}", 0.05 + 0.85 * (bi + 1) / len(blocks))

    frames = []
    bounds = None
    for lv in levels:
        p, bounds = to_web_mercator(small[lv], meta, 0, 0, cell * k)
        share = min(0.02 + lv / 150.0 * 0.28, 0.30)
        v = p[p > 0]
        qs = np.quantile(v, [1 - share, 1 - share / 2, 1 - share / 4, 1 - share / 10])
        rgba = np.zeros((OH, OW, 4), dtype=np.uint8)
        for lo, hi, col in ((qs[0], qs[1], (255, 235, 130)), (qs[1], qs[2], (255, 170, 60)),
                            (qs[2], qs[3], (240, 90, 40)), (qs[3], 2.0, (190, 20, 30))):
            msk = (p >= lo) & (p < hi)
            rgba[msk] = (*col, 200)
        name = f"risk_{int(lv):03d}.png"
        Image.fromarray(rgba).save(a.out / name, optimize=True)
        frames.append({"mm": lv, "file": name, "risky_pct": round(share * 100, 1)})
    (a.out / "frames.json").write_text(json.dumps(
        {"bounds": bounds, "frames": frames},
        ensure_ascii=False, indent=1), encoding="utf-8")
    note(f"완료 — {len(frames)}장, {OH} x {OW} 픽셀", 1.0)


if __name__ == "__main__":
    main()
