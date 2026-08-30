#!/usr/bin/env python3
"""전국 침수 위험 지도를 30 m 그대로, 웹 지도 타일로.

전국을 한 장의 그림으로 만들면 1억 9,600만 픽셀이다. 가로 세로는 브라우저
한계 안이지만 풀어놓으면 786 MB이고, 강수 단계가 일곱 장이라 5.5 GB를 한꺼번에
들고 있어야 한다. 그래서 지금까지는 8x8로 묶어 240 m 로 내보냈다. 확대해도
30 m 칸이 나오지 않는 이유가 그것이다.

웹 지도가 원래 쓰는 방법을 쓰면 된다. 그림을 256 픽셀 타일로 잘라 두고 화면에
보이는 것만 내려받는다. 한 화면은 언제나 20~30장이므로 전국이 30 m 여도 부담이
같다. 줌 12가 30.9 m/픽셀이라 우리 격자와 거의 정확히 맞고, 그 위로는 같은
타일을 확대해 보여주면 칸이 네모로 커진다.

낮은 줌은 위 단계 타일 넷을 2x2로 묶어 만드는데, 평균이 아니라 '가장 위험한
쪽'을 남긴다. 평균을 내면 도로 한 칸짜리 위험이 주변에 희석돼 사라지고, 그런
자리를 보자고 30 m로 내려온 것이기 때문이다.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj
from PIL import Image
from xgboost import XGBClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_flood_map_national import (          # noqa: E402
    G30, USE, STATIC, MODEL_KW, RATIO_1H_6H, PLATEAU_MM)

ROOT = Path(__file__).resolve().parents[1]
WORLD = 20037508.342789244
TILE = 256
# 색은 확률이 아니라 그 강수에서의 순위다. 위험한 쪽일수록 뒤에 온다.
PAL = np.array([[0, 0, 0, 0], [255, 235, 130, 200], [255, 170, 60, 200],
                [240, 90, 40, 200], [190, 20, 30, 200]], dtype=np.uint8)


def bands_from_rgba(a: np.ndarray) -> np.ndarray:
    """저장한 타일에서 위험 등급을 되읽는다. 피라미드를 쌓을 때 쓴다."""
    b = np.zeros(a.shape[:2], dtype=np.uint8)
    for i in range(1, len(PAL)):
        m = (a[..., 0] == PAL[i, 0]) & (a[..., 1] == PAL[i, 1]) & (a[..., 2] == PAL[i, 2])
        b[m] = i
    return b


def train(table: Path, note):
    note("학습 표 읽는 중", 0.0)
    d = pd.read_csv(table)
    d["event"] = d.event.astype(str)
    sh = d[d.flooded == 1].groupby("event").rain_6h.apply(lambda s: (s < 1).mean())
    d = d[~d.event.isin(sh[sh >= 0.5].index)]
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    d = d.dropna(subset=USE)
    pos = max(int(d.flooded.sum()), 1)
    w = (len(d) - pos) / pos
    m = XGBClassifier(eval_metric="logloss", n_jobs=10, scale_pos_weight=w, **MODEL_KW)
    m.fit(d[USE], d.flooded)
    med = {c: float(d[c].median()) for c in USE}
    return m, w, med


def score(m, w, med, levels, work: Path, rows_per_block: int, note):
    """30 m 격자 전체를 강수 단계마다 채점해 디스크에 눕힌다."""
    meta = json.loads((G30 / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    R, C, cell = meta["rows"], meta["cols"], meta["cell_m"]
    layers = {n: np.load(G30 / f"{n}.npy", mmap_mode="r") for n in STATIC}
    # 40 mm 위는 값을 유지하기로 했으므로 60/80/100/150 이 모델에는 전부 40 으로
    # 들어간다. 슬라이더는 일곱 칸이지만 서로 다른 채점은 셋뿐이다.
    effs = sorted({min(lv, PLATEAU_MM) for lv in levels})
    out = {e: np.lib.format.open_memmap(work / f"p_{int(e):03d}.npy", mode="w+",
                                        dtype="float16", shape=(R, C)) for e in effs}
    i6, i1 = USE.index("rain_6h"), USE.index("rain_1h")
    blocks = list(range(0, R, rows_per_block))
    t0 = time.time()
    for bi, r0 in enumerate(blocks):
        r1 = min(r0 + rows_per_block, R)
        h = r1 - r0
        el = np.asarray(layers["elevation"][r0:r1], dtype="float32")
        # 바다와 격자 밖이 전체의 41%다. 채점하고 나서 버리느니 아예 빼고 간다.
        idx = np.flatnonzero((np.isfinite(el) & (el > 0)).ravel())
        del el
        if len(idx) == 0:
            note(f"채점 {bi+1}/{len(blocks)} — 전부 바다", 0.05 + 0.55 * (bi + 1) / len(blocks))
            continue
        # 강수만 바뀌므로 나머지 열은 블록마다 한 번만 채운다. 단계마다 다시
        # 쌓으면 21열짜리 1 GB 복사를 일곱 번 하는 셈이 된다.
        X = np.empty((len(idx), len(USE)), dtype="float32")
        for j, n in enumerate(USE):
            if n in ("rain_6h", "rain_1h"):
                continue
            v = np.asarray(layers[n][r0:r1], dtype="float32").ravel()[idx]
            X[:, j] = np.where(np.isfinite(v), v, med[n])
        for eff in effs:
            X[:, i6] = eff
            X[:, i1] = eff * RATIO_1H_6H
            p = m.predict_proba(X)[:, 1]
            odds = p / np.maximum(1 - p, 1e-9) / w      # 확률로 되돌린다
            full = np.zeros(h * C, dtype="float32")
            full[idx] = odds / (1 + odds)
            out[eff][r0:r1] = full.reshape(h, C)
        el_s = (time.time() - t0) / (bi + 1) * (len(blocks) - bi - 1)
        note(f"채점 {bi+1}/{len(blocks)} — 남은 시간 {el_s/60:.0f}분",
             0.05 + 0.55 * (bi + 1) / len(blocks))
    for f in out.values():
        f.flush()
    return meta


def cut_zmax(meta, levels, work: Path, tiles: Path, z: int, note):
    """줌 12 타일. 목적지 픽셀마다 원본 칸을 되짚는 최근접 표본이다."""
    R, C, cell = meta["rows"], meta["cols"], meta["cell_m"]
    ox, oyt = meta["origin_x"], meta["origin_y_top"]
    fwd = pyproj.Transformer.from_crs("EPSG:5179", "EPSG:3857", always_xy=True)
    inv = pyproj.Transformer.from_crs("EPSG:3857", "EPSG:5179", always_xy=True)

    # 5179 사각형은 웹 좌표에서 사다리꼴이라 네 변을 훑어 바깥 상자를 잡는다
    xs = ox + np.arange(0, C + 1, 200) * cell
    ys = oyt - np.arange(0, R + 1, 200) * cell
    bx = np.concatenate([xs, xs, np.full(len(ys), xs[0]), np.full(len(ys), xs[-1])])
    by = np.concatenate([np.full(len(xs), ys[0]), np.full(len(xs), ys[-1]), ys, ys])
    mx, my = fwd.transform(bx, by)
    res = 2 * WORLD / (TILE * 2 ** z)
    tx0 = int((mx.min() + WORLD) / res // TILE); tx1 = int((mx.max() + WORLD) / res // TILE)
    ty0 = int((WORLD - my.max()) / res // TILE); ty1 = int((WORLD - my.min()) / res // TILE)

    # 40 mm 위 다섯 단계는 같은 확률 판을 공유한다. 달라지는 것은 칠하는 넓이뿐이다.
    eff_of = {lv: min(lv, PLATEAU_MM) for lv in levels}
    arr = {e: np.load(work / f"p_{int(e):03d}.npy", mmap_mode="r")
           for e in sorted(set(eff_of.values()))}
    pm = {lv: arr[eff_of[lv]] for lv in levels}
    samp = {e: (lambda v: v[v > 0])(np.asarray(a[::5], dtype="float32").ravel())
            for e, a in arr.items()}
    qs = {}
    for lv in levels:
        share = min(0.02 + lv / 150.0 * 0.28, 0.30)
        qs[lv] = np.quantile(samp[eff_of[lv]],
                             [1 - share, 1 - share / 2, 1 - share / 4, 1 - share / 10])
    del samp

    px = (np.arange(tx0 * TILE, (tx1 + 1) * TILE) + 0.5) * res - WORLD
    written = 0
    for n, ty in enumerate(range(ty0, ty1 + 1)):
        py = WORLD - (np.arange(ty * TILE, (ty + 1) * TILE) + 0.5) * res
        MX, MY = np.meshgrid(px, py)
        sx, sy = inv.transform(MX.ravel(), MY.ravel())
        cc = np.floor((sx - ox) / cell).astype(np.int32)
        rr = np.floor((oyt - sy) / cell).astype(np.int32)
        ok = (rr >= 0) & (rr < R) & (cc >= 0) & (cc < C)
        flat = (rr.astype(np.int64) * C + cc)[ok]
        for lv in levels:
            vals = np.zeros(len(ok), dtype="float32")
            vals[ok] = pm[lv].reshape(-1)[flat]
            q = qs[lv]
            b = np.zeros(len(vals), dtype=np.uint8)
            b[vals >= q[0]] = 1
            b[vals >= q[1]] = 2
            b[vals >= q[2]] = 3
            b[vals >= q[3]] = 4
            b = b.reshape(TILE, -1)
            for i, tx in enumerate(range(tx0, tx1 + 1)):
                sl = b[:, i * TILE:(i + 1) * TILE]
                if not sl.any():
                    continue
                d = tiles / f"{int(lv):03d}/{z}/{tx}"
                d.mkdir(parents=True, exist_ok=True)
                Image.fromarray(PAL[sl]).save(d / f"{ty}.png", optimize=True)
                written += 1
        note(f"줌 {z} 자르는 중 {n+1}/{ty1-ty0+1} — {written:,}장",
             0.60 + 0.30 * (n + 1) / (ty1 - ty0 + 1))
    return written


def build_pyramid(tiles: Path, levels, zmax: int, zmin: int, note):
    """위 단계 넷을 2x2로 묶되 가장 위험한 쪽을 남긴다."""
    total = 0
    for lv in levels:
        root = tiles / f"{int(lv):03d}"
        for z in range(zmax - 1, zmin - 1, -1):
            kids = {(int(p.parent.name) // 2, int(p.stem) // 2)
                    for p in (root / str(z + 1)).glob("*/*.png")}
            for tx, ty in kids:
                par = np.zeros((TILE, TILE), dtype=np.uint8)
                for i in range(2):
                    for j in range(2):
                        f = root / f"{z+1}/{2*tx+i}/{2*ty+j}.png"
                        if not f.exists():
                            continue
                        b = bands_from_rgba(np.array(Image.open(f)))
                        par[j * 128:(j + 1) * 128, i * 128:(i + 1) * 128] = \
                            b.reshape(128, 2, 128, 2).max(axis=(1, 3))
                if not par.any():
                    continue
                d = root / f"{z}/{tx}"
                d.mkdir(parents=True, exist_ok=True)
                Image.fromarray(PAL[par]).save(d / f"{ty}.png", optimize=True)
                total += 1
        note(f"낮은 줌 쌓는 중 — {int(lv)} mm 까지 {total:,}장", 0.90)
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--levels", default="0,20,40,60,80,100,150")
    ap.add_argument("--zoom-max", type=int, default=12)
    ap.add_argument("--zoom-min", type=int, default=6)
    ap.add_argument("--rows-per-block", type=int, default=1200)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_poly.csv")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs/flood-map-tiles")
    ap.add_argument("--work", type=Path, default=ROOT / "data/interim/flood-tiles-work")
    ap.add_argument("--skip-scoring", action="store_true",
                    help="채점 결과가 이미 있으면 타일만 다시 만든다")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    a.work.mkdir(parents=True, exist_ok=True)
    status = a.out / "status.json"

    def note(msg, frac=None):
        d = {"message": msg, "updated": time.strftime("%H:%M:%S")}
        if frac is not None:
            d["percent"] = round(frac * 100, 1)
        status.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        print(msg, flush=True)

    levels = [float(v) for v in a.levels.split(",")]
    if a.skip_scoring:
        meta = json.loads((G30 / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
        note("채점 건너뜀 — 기존 결과 사용", 0.60)
    else:
        m, w, med = train(a.table, note)
        note("학습 완료", 0.05)
        meta = score(m, w, med, levels, a.work, a.rows_per_block, note)

    tiles = a.out / "tiles"
    n12 = cut_zmax(meta, levels, a.work, tiles, a.zoom_max, note)
    nlo = build_pyramid(tiles, levels, a.zoom_max, a.zoom_min, note)

    # 지도를 처음 맞출 범위. 5179 사각형은 위경도에서 사다리꼴이라 네 변을 훑는다
    R, C, cell = meta["rows"], meta["cols"], meta["cell_m"]
    ox, oyt = meta["origin_x"], meta["origin_y_top"]
    t84 = pyproj.Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    xs = ox + np.arange(0, C + 1, 200) * cell
    ys = oyt - np.arange(0, R + 1, 200) * cell
    bx = np.concatenate([xs, xs, np.full(len(ys), xs[0]), np.full(len(ys), xs[-1])])
    by = np.concatenate([np.full(len(xs), ys[0]), np.full(len(xs), ys[-1]), ys, ys])
    lo, la = t84.transform(bx, by)

    (a.out / "frames.json").write_text(json.dumps({
        "bounds": [[float(la.min()), float(lo.min())],
                   [float(la.max()), float(lo.max())]],
        "template": "tiles/{mm}/{z}/{x}/{y}.png",
        "zoom_native": a.zoom_max, "zoom_min": a.zoom_min,
        "cell_m": meta["cell_m"],
        "frames": [{"mm": lv, "dir": f"{int(lv):03d}",
                    "risky_pct": round(min(0.02 + lv / 150.0 * 0.28, 0.30) * 100, 1)}
                   for lv in levels],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    note(f"완료 — 줌 {a.zoom_max} {n12:,}장, 낮은 줌 {nlo:,}장", 1.0)


if __name__ == "__main__":
    main()
