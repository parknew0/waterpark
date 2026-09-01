#!/usr/bin/env python3
"""한 번도 안 가본 지역에서 통하는가. 시도를 통째로 빼고 잰다.

설정을 손질해 +1.94p 를 얻었다. 그것은 폭풍을 감추고 잰 값이므로 \033[1m시간에 대해서는\033[0m
이미 일반화를 보였다. 남은 것은 공간이다 -- 우리 정답지는 조사가 이뤄진 곳에서만
오는데 지도는 전국을 칠한다.

도로 침수 위험지점으로도 재 봤지만 그 시험지는 장소의 종류와 정답지의 출처가
동시에 다르다. 결과가 나빠도 둘 중 무엇 탓인지 가릴 수 없다.

시도를 통째로 빼면 장소의 종류도 정답지 출처도 같고 \033[1m지역만\033[0m 다르다. 공간
일반화만 깨끗하게 잰다. 그리고 옛 설정과 손질한 설정을 같은 시험지에서 견준다.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
G30 = ROOT / "data/interim/grid30"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_flood_map_national import USE, MODEL_KW      # noqa: E402
RANKED = ["elevation", "rel_500m", "sink_depth", "slope_deg", "flow_acc",
          "impervious", "dist_stream", "sewer_density"]
QCOLS = [f"q_{c}" for c in RANKED]
from eval_hyper_sweep import prep, capture              # noqa: E402
BEST = ROOT / "outputs/flooded-building-register/best_model_kw.json"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_146.csv")
    ap.add_argument("--sample", type=float, default=0.35)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--min-pos", type=int, default=2000, help="채점할 시도의 최소 침수 칸")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "outputs/flooded-building-register/spatial_holdout.json")
    a = ap.parse_args()

    tuned = dict(MODEL_KW)
    if BEST.exists():
        j = json.loads(BEST.read_text(encoding="utf-8"))
        tuned = j["kw"]; print(f"손질한 설정: {j['이름']} (폭풍 감추기 상위5% {j['상위5%']:.1f}%)")

    head = pd.read_csv(a.table, nrows=2)
    has_q = [c for c in QCOLS if c in head.columns]
    d = prep(a.table, a.sample, 6, extra=("lon", "lat", *has_q))
    if has_q:
        print(f"지역 내 순위 열 {len(has_q)}개 발견 -> 견줄 조건에 넣는다")
    # 시도는 시군구 격자의 앞 두 자리로 얻는다
    g = json.loads((G30 / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    sid = np.load(G30 / "sgg_id.npy", mmap_mode="r")
    ix = json.loads((G30 / "sgg_index.json").read_text(encoding="utf-8"))["index"]
    rev = {v: k.split("|")[0] for k, v in ix.items()}
    t = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    x, y = t.transform(d.lon.to_numpy(), d.lat.to_numpy()) if "lon" in d else (None, None)
    if x is None:
        raise SystemExit("표에 lon/lat 이 없다")
    r = ((g["origin_y_top"] - y) // g["cell_m"]).astype(np.int64)
    c = ((x - g["origin_x"]) // g["cell_m"]).astype(np.int64)
    ok = (r >= 0) & (r < g["rows"]) & (c >= 0) & (c < g["cols"])
    prov = np.full(len(d), "", dtype=object)
    prov[ok] = [rev.get(int(v), "") for v in np.asarray(sid)[r[ok], c[ok]]]
    d = d.assign(prov=prov)
    d = d[d.prov != ""]
    cnt = d.groupby("prov").flooded.sum().sort_values(ascending=False)
    tests = [p for p, n in cnt.items() if n >= a.min_pos]
    print(f"\n행 {len(d):,}  시도 {d.prov.nunique()}개")
    print(f"채점할 시도 {len(tests)}개 (침수 {a.min_pos}칸 이상):")
    for p in tests:
        print(f"  {p:<14} 침수 {int(cnt[p]):,}")
    print(flush=True)

    res = {k: [] for k in ("옛 설정", "손질한 설정", "손질+지역순위",
                           "표고만", "주변대비 높이만")}
    if not has_q:
        res.pop("손질+지역순위")
    t0 = time.time()
    for p in tests:
        tr, te = d[d.prov != p], d[d.prov == p]
        pos = max(int(tr.flooded.sum()), 1)
        w = (len(tr) - pos) / pos
        preds = {}
        sets = [("옛 설정", MODEL_KW, list(USE)), ("손질한 설정", tuned, list(USE))]
        if has_q:
            sets.append(("손질+지역순위", tuned, list(USE) + has_q))
        for name, kw, cols in sets:
            m = XGBClassifier(eval_metric="logloss", n_jobs=a.jobs,
                              scale_pos_weight=w, **kw)
            m.fit(tr[cols], tr.flooded)
            preds[name] = m.predict_proba(te[cols])[:, 1]
        preds["표고만"] = -te.elevation.to_numpy()
        # 절대 표고는 시도마다 폭이 다섯 배 달라 "산이냐 평지냐"를 재는 셈이 된다.
        # 물리적으로 맞는 자는 주변 대비 높이다.
        preds["주변대비 높이만"] = -te.rel_500m.to_numpy()
        for k, q in preds.items():
            res[k].append({"prov": p, "auc": float(roc_auc_score(te.flooded, q)),
                           "top5": float(capture(te.flooded, q)) * 100})
        print(f"  {p:<14} " + "  ".join(f"{k} {res[k][-1]['top5']:5.1f}%" for k in res) +
              f"   ({(time.time()-t0)/60:.0f}분)", flush=True)

    print("\n=== 한 번도 안 가본 시도에서 (상위 5% 포착) ===")
    for k, v in res.items():
        print(f"  {k:<12} AUC {np.mean([x['auc'] for x in v]):.4f}   "
              f"상위5% {np.mean([x['top5'] for x in v]):5.1f}%")
    base = np.array([x["top5"] for x in res["옛 설정"]])
    print("\n=== 옛 설정 대비 (같은 시도끼리) ===")
    for k in [x for x in res if x != "옛 설정"]:
        dd = np.array([x["top5"] for x in res[k]]) - base
        se = dd.std(ddof=1) / np.sqrt(len(dd))
        v = "낫다" if dd.mean() > 2*se else ("못하다" if dd.mean() < -2*se else "판정불가")
        print(f"  {k:<12} {dd.mean():+.2f}p ± {se:.2f}   "
              f"이긴 시도 {int((dd>0).sum())}/{len(dd)}  -> {v}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
