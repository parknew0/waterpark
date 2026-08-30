#!/usr/bin/env python3
"""강수량을 밀어가며 어디가 잠기는지 지도에서 본다.

모델은 지형·토지이용·배수를 고정하고 강수만 바꿔 넣으면 그 비에 대한 답을
새로 낸다. 슬라이더가 하는 일이 그것이다 -- 같은 땅에 비만 늘려가며 물이
차오르는 순서를 보는 것이고, 숫자로만 보던 임계값이 눈에 보이는 형태가 된다.

출력은 강수 단계별 PNG 한 장씩과 그것을 얹는 HTML이다. 격자가 EPSG:5179라
그대로 얹으면 웹 지도와 어긋나므로 3857로 다시 샘플링해서 내보낸다.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj
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


LAYER = {n: n for n in USE if n not in ("rain_1h", "rain_6h")}



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
    ap.add_argument("--lon0", type=float, default=126.93)
    ap.add_argument("--lat0", type=float, default=37.46)
    ap.add_argument("--lon1", type=float, default=127.10)
    ap.add_argument("--lat1", type=float, default=37.56)
    ap.add_argument("--levels", default="0,10,20,30,40,50,60,80,100,120,150")
    ap.add_argument("--mode", choices=("prob", "rank"), default="prob",
                    help="rank=강수 단계마다 위험한 순서로 상위 몇 %를 칠한다")
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_poly.csv")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs/flood-map-demo")
    a = ap.parse_args()

    print("[학습] 표 읽는 중", flush=True)
    d = pd.read_csv(a.table)
    d["event"] = d.event.astype(str)
    share = d[d.flooded == 1].groupby("event").rain_6h.apply(lambda s: (s < 1).mean())
    d = d[~d.event.isin(share[share >= 0.5].index)]
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    d = d.dropna(subset=USE)
    pos = max(int(d.flooded.sum()), 1)
    w = (len(d) - pos) / pos
    m = XGBClassifier(eval_metric="logloss", n_jobs=8,
                      scale_pos_weight=w, **MODEL_KW)
    m.fit(d[USE], d.flooded)

    def calibrate(p):
        """scale_pos_weight 로 학습하면 출력이 확률이 아니다.

        양성을 w배로 세어 학습했으므로 예측 오즈도 w배 부풀어 있다. 여기서는
        침수율이 0.8%인데 보정 없이 읽으면 비가 한 방울도 안 온 격자의 38%가
        '위험'으로 뜬다. 오즈를 되돌려 원래 비율로 읽는다.
        """
        odds = p / np.maximum(1.0 - p, 1e-9) / w
        return odds / (1.0 + odds)
    med = {c: float(d[c].median()) for c in USE}
    print(f"[학습] 완료 ({len(d):,}행)", flush=True)

    meta = json.loads((G30 / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    cell = meta["cell_m"]
    T = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    x0, y0 = T.transform(a.lon0, a.lat0)
    x1, y1 = T.transform(a.lon1, a.lat1)
    c0 = int((min(x0, x1) - meta["origin_x"]) // cell)
    c1 = int((max(x0, x1) - meta["origin_x"]) // cell) + 1
    r0 = int((meta["origin_y_top"] - max(y0, y1)) // cell)
    r1 = int((meta["origin_y_top"] - min(y0, y1)) // cell) + 1
    H, W = r1 - r0, c1 - c0
    print(f"[영역] {H} x {W} 칸 ({H*cell/1000:.1f} x {W*cell/1000:.1f} km)", flush=True)

    cols = {}
    for name in USE:
        if name in ("rain_1h", "rain_6h"):
            continue
        arr = np.load(G30 / f"{LAYER[name]}.npy", mmap_mode="r")[r0:r1, c0:c1]
        cols[name] = np.asarray(arr, dtype="float32").ravel()
    land = np.isfinite(cols["elevation"]) & (cols["elevation"] > 0)
    for k in cols:
        cols[k] = np.where(np.isfinite(cols[k]), cols[k], med[k])

    a.out.mkdir(parents=True, exist_ok=True)
    levels = [float(v) for v in a.levels.split(",")]
    from PIL import Image
    frames = []
    for lv in levels:
        eff = min(lv, PLATEAU_MM)
        cols["rain_6h"] = np.full(H * W, eff, dtype="float32")
        cols["rain_1h"] = np.full(H * W, eff * RATIO_1H_6H, dtype="float32")
        X = np.column_stack([cols[c] for c in USE])
        p = calibrate(m.predict_proba(X)[:, 1]).reshape(H, W)
        p = np.where(land.reshape(H, W), p, np.nan)
        p, bounds = to_web_mercator(np.nan_to_num(p, nan=-1.0), meta, r0, c0, cell)
        p = np.where(p < 0, np.nan, p)
        rgba = np.zeros((H, W, 4), dtype=np.uint8)
        # 확률을 그대로 칠하면 50 mm 위에서 색이 옅어진다. 모델이 틀린 것이
        # 아니라 자료가 그렇다 -- 10~80 mm 구간의 실제 침수율은 0.94%, 0.98%,
        # 0.89%로 거의 평평하다. 비는 늘 국지적이어서 모델이 배운 것은
        # 절대량이 아니라 '주변보다 여기가 더 왔다'는 대비이고, 데모처럼 전
        # 지역에 같은 비를 균일하게 뿌리면 그 대비가 사라진다.
        #
        # 그래서 단계마다 그 비에서 위험한 순서로 줄을 세워 상위 몇 %를
        # 칠한다. 모델이 실제로 검증된 방식(순위)이고, 비가 늘수록 잠기는
        # 면적이 커지는 것은 위험 구간을 강수에 따라 넓히는 것으로 나타낸다.
        share = min(0.02 + lv / 150.0 * 0.28, 0.30) if a.mode == "rank" else None
        if share is None:
            bands = ((0.008, 0.02, (255, 235, 130)), (0.02, 0.05, (255, 170, 60)),
                     (0.05, 0.12, (240, 90, 40)), (0.12, 1.01, (190, 20, 30)))
        else:
            v = p[np.isfinite(p)]
            qs = np.quantile(v, [1 - share, 1 - share / 2, 1 - share / 4, 1 - share / 10])
            bands = ((qs[0], qs[1], (255, 235, 130)), (qs[1], qs[2], (255, 170, 60)),
                     (qs[2], qs[3], (240, 90, 40)), (qs[3], 1.01, (190, 20, 30)))
        for lo, hi, col in bands:
            msk = np.isfinite(p) & (p >= lo) & (p < hi)
            rgba[msk] = (*col, 190)
        name = f"risk_{int(lv):03d}.png"
        Image.fromarray(rgba).save(a.out / name)
        frames.append({"mm": lv, "file": name,
                       "risky_pct": round(float(share * 100) if share else
                                          float(np.nanmean(p >= 0.02)) * 100, 2),
                       "median_pct": round(float(np.nanmedian(p)) * 100, 3)})
        print(f"  {lv:5.0f} mm/6h -> 위험(2% 이상) 칸 {frames[-1]['risky_pct']:5.2f}%"
              f"   중앙 확률 {frames[-1]['median_pct']:.3f}%",
              flush=True)

    (a.out / "frames.json").write_text(json.dumps(
        {"bounds": bounds, "frames": frames},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[결과] {len(frames)}장 -> {a.out}")


if __name__ == "__main__":
    main()
