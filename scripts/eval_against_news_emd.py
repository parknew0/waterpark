#!/usr/bin/env python3
"""기사 채점을 읍면동 눈금으로 다시. 시군구는 너무 굵었는가.

시군구 단위에서 우리 모델은 강수량만 쓴 것보다 나빴다. 남은 해석은 "시군구끼리
비교하는 시험인데 우리 모델은 한 동네 안에서 칸끼리 가리도록 배웠다" 였는데,
그것은 아직 가설이었다. 읍면동은 중앙 넓이 4 km2 로 시군구(384 km2)보다
\033[1m106 배\033[0m 가늘다. 여기서도 지면 그 해석은 버려야 한다.

기사 본문에서 읍면동 이름을 뽑아 시군구와 짝지어 격자에 붙였다. 같은 이름이
전국에 여럿 있으므로 (신촌동만 여러 곳) 시군구가 맞는 것만 인정하고, 못 가린
138 건은 버렸다. 양성 1,325 덩어리, 122 일.

시군구 판에서 배운 것을 그대로 가져왔다.
  - 강수만 쓰는 기준선을 반드시 나란히 놓는다. 그것을 못 넘으면 지형은 헛일이다.
  - 넓이에 비례하는 통계(평균 확률, 문턱 넘은 비율)와 극값(최댓값, p99) 을 함께 낸다.
  - 학습에 쓴 날은 따로 뗀다.
  - 비가 거의 안 온 곳은 물을 일이 없으므로 뺀다.
"""
from __future__ import annotations
import argparse, ast, json, pickle, re, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
G30 = ROOT / "data/interim/grid30"
RAD = ROOT / "data/interim/radar"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_flood_map_national import USE, MODEL_KW, RATIO_1H_6H, PLATEAU_MM  # noqa: E402

STATIC = [c for c in USE if c not in ("rain_1h", "rain_6h")]
PAT = re.compile(r"[가-힣]{2,5}(?:읍|면|동)\b")


def load(name, path):
    import importlib.util
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    return m


def article_bags(keys):
    import collections
    by_name = collections.defaultdict(list)
    for k in keys:
        by_name[k.split("|")[-1]].append(k)
    fs = sorted((ROOT / "data/raw/env-bigdata").glob("flood_articles_*.csv"))
    a = pd.concat([pd.read_csv(f, encoding="utf-8-sig") for f in fs])
    a = a[a.WEATHER_FACTOR == "홍수"].copy()
    a["d"] = pd.to_datetime(a.NEWS_WRT_YMD, errors="coerce")
    a = a.dropna(subset=["d"])

    def lst(s):
        if not isinstance(s, str) or s.strip() == "-999":
            return []
        try:
            return [x for x in ast.literal_eval(s) if isinstance(x, str)]
        except Exception:
            return []
    rows = []
    for d0, sg, txt in zip(a.d, a.SGG_CLSF, a.NEWS_TXT.astype(str)):
        sggs = set(lst(sg))
        for nm in set(PAT.findall(txt)):
            cand = by_name.get(nm, [])
            if not cand:
                continue
            pick = [c for c in cand if c.split("|")[0] in sggs] or (cand if len(cand) == 1 else [])
            for c in pick:
                # 새벽 침수는 이튿날 기사가 된다
                rows.append((d0.strftime("%Y%m%d"), c))
                rows.append(((d0 - pd.Timedelta(days=1)).strftime("%Y%m%d"), c))
    b = pd.DataFrame(rows, columns=["day", "key"])
    return b.groupby(["day", "key"]).size().rename("articles").reset_index()


def report(s, label, out):
    if len(s) < 200 or s.hit.nunique() < 2:
        print(f"\n[{label}] 표본 부족 ({len(s)})"); return
    base = float(s.hit.mean())
    k = max(int(len(s) * 0.05), 1)
    print(f"\n\033[1m[{label}]\033[0m 덩어리 {len(s):,}개, 기사 난 것 {base*100:.2f}%")
    print(f"  {'무엇으로 순위를 매겼나':<26}{'AUC':>8}{'상위5% 적중':>12}{'기저대비':>9}")
    got = {}
    for name, col in (("우리 (평균확률)", "pmean"), ("우리 (5% 넘는 칸 비율)", "f05"),
                      ("우리 (p99)", "p99"), ("우리 (최댓값)", "pmax"),
                      ("── 강수량만 (최대)", "rain"), ("── 강수량만 (평균)", "rain_mean"),
                      ("── 시가지 비율만", "built")):
        if col not in s or s[col].nunique() < 2:
            continue
        auc = roc_auc_score(s.hit, s[col])
        top = s.nlargest(k, col).hit.mean()
        got[col] = {"auc": float(auc), "top5": float(top), "lift": float(top / max(base, 1e-9))}
        print(f"  {name:<26}{auc:8.4f}{top*100:11.2f}%{top/max(base,1e-9):8.1f}배")
    if "pmean" in got and "rain" in got:
        best = max(got[c]["auc"] for c in ("pmean", "f05", "p99", "pmax") if c in got)
        d = best - got["rain"]["auc"]
        print(f"\n  \033[1m우리 최고 - 강수량만 = AUC {d:+.4f}\033[0m"
              f"   {'우리가 낫다' if d > 0.01 else '구별 안 됨' if abs(d) <= 0.01 else '강수량만도 못하다'}")
    out[label] = {"덩어리": int(len(s)), "기사난비율": base, "지표": got}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_all_full.csv")
    ap.add_argument("--per-emd", type=int, default=1200)
    ap.add_argument("--rain-min", type=float, default=10.0)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "outputs/flooded-building-register/news_eval_emd.json")
    a = ap.parse_args()

    idx = json.loads((G30 / "emd_index.json").read_text(encoding="utf-8"))["index"]
    name_of = {v: k for k, v in idx.items()}
    bags = article_bags(list(idx))
    print(f"기사 덩어리 {len(bags):,}개  ({bags.day.nunique()}일, {bags.key.nunique()}개 읍면동)")

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
    train_days = set(d.event)
    del d
    print(f"학습 완료 (학습에 쓴 날 {len(train_days)}개)", flush=True)

    g = json.loads((G30 / "grid_meta30.json").read_text(encoding="utf-8"))["grid"]
    R, C, cell = g["rows"], g["cols"], g["cell_m"]
    emd = np.load(G30 / "emd_id.npy", mmap_mode="r")
    el = np.load(G30 / "elevation.npy", mmap_mode="r")
    step = 2                              # 읍면동은 작으므로 촘촘히 훑는다
    sub = np.asarray(emd[::step, ::step])
    sube = np.asarray(el[::step, ::step], dtype="float32")
    ok = (sub > 0) & np.isfinite(sube) & (sube > 0)
    ids = sub[ok]
    rr, cc = (x * step for x in np.nonzero(ok))
    order = np.argsort(ids, kind="stable")
    ids, rr, cc = ids[order], rr[order], cc[order]
    uniq, starts = np.unique(ids, return_index=True)
    edges = list(starts) + [len(ids)]
    rng = np.random.default_rng(0)
    sel = np.concatenate([rng.choice(np.arange(edges[i], edges[i+1]),
                                     min(a.per_emd, edges[i+1]-edges[i]), replace=False)
                          for i in range(len(uniq))])
    allr, allc, owner = rr[sel], cc[sel], ids[sel]
    print(f"읍면동 {len(uniq):,}개, 표본 {len(sel):,}칸", flush=True)

    cols = {}
    for n in STATIC:
        v = np.asarray(np.load(G30 / f"{n}.npy", mmap_mode="r")[allr, allc], dtype="float32")
        cols[n] = np.where(np.isfinite(v), v, med[n])
    X = np.empty((len(allr), len(USE)), dtype="float32")
    for j, n in enumerate(USE):
        if n not in ("rain_1h", "rain_6h"):
            X[:, j] = cols[n]
    i6, i1 = USE.index("rain_6h"), USE.index("rain_1h")
    built = cols["built_ratio"]

    bett = load("bett", ROOT / "scripts/build_event_training_table.py")
    rate_fn = load("crr", ROOT / "scripts/collect_radar_rainfall.py").rain_rate
    rlon = np.fromfile(RAD / "hsr_lon.bin", dtype="<f4")[1:]
    rlat = np.fromfile(RAD / "hsr_lat.bin", dtype="<f4")[1:]
    good = np.isfinite(rlon) & np.isfinite(rlat) & (rlon > 120) & (rlon < 133)
    ridx = np.flatnonzero(good)
    import pyproj
    to84 = pyproj.Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    lon, lat = to84.transform(g["origin_x"] + (allc + 0.5) * cell,
                              g["origin_y_top"] - (allr + 0.5) * cell)
    near = ridx[cKDTree(np.c_[rlon[good]*88_000, rlat[good]*111_000])
                .query(np.c_[lon*88_000, lat*111_000], k=1)[1]]

    # 레이더 격자는 664 만 칸인데 우리 표본이 가리키는 것은 36 만 칸(5.5%) 뿐이다.
    # 전부 계산하면 하루 38 초가 걸리고 그중 33 초가 버리는 계산이다. 쓸 칸만
    # 먼저 골라내면 같은 값을 4 초에 얻는다.
    keep = np.unique(near)
    back = np.searchsorted(keep, near)          # near -> 골라낸 배열에서의 자리
    print(f"레이더 칸 {len(keep):,}개만 계산한다 (전체 6,640,705 개 중 "
          f"{len(keep)/6_640_705*100:.1f}%)", flush=True)

    rows, t0 = [], time.time()
    files = sorted((RAD / "grids_full").glob("rain_*_grid.npz"))
    for n, f in enumerate(files):
        ev = f.stem.replace("rain_", "").replace("_grid", "")
        z = np.load(f)
        spans = z["span_min"].astype("float64")
        raw = z["grid"].reshape(len(spans), -1)[:, keep].astype("float32") / 100.0
        series = rate_fn(raw)
        del raw
        tot = bett.accumulate(series, spans, forward=False)
        del series
        rain = tot[6][back]
        X[:, i6] = np.minimum(rain, PLATEAU_MM)
        X[:, i1] = X[:, i6] * RATIO_1H_6H
        p = m.predict_proba(X)[:, 1]
        odds = p / np.maximum(1 - p, 1e-9) / w
        p = odds / (1 + odds)
        df = pd.DataFrame({"emd": owner, "p": p, "rain": rain, "built": built})
        agg = df.groupby("emd").agg(pmax=("p", "max"), p99=("p", lambda s: np.quantile(s, .99)),
                                    pmean=("p", "mean"),
                                    f05=("p", lambda s: float((s > 0.05).mean())),
                                    rain=("rain", "max"), rain_mean=("rain", "mean"),
                                    built=("built", "mean")).reset_index()
        agg["day"] = ev
        agg["key"] = [name_of.get(int(i), "") for i in agg.emd]
        rows.append(agg)
        if (n + 1) % 20 == 0 or n == len(files) - 1:
            print(f"  {n+1}/{len(files)}  ({(time.time()-t0)/60:.0f}분)", flush=True)
    res = pd.concat(rows).merge(bags, on=["day", "key"], how="left")
    res["hit"] = res.articles.notna().astype(int)
    res["unseen"] = (~res.day.isin(train_days)).astype(int)

    out = {}
    wet = res[res.rain >= a.rain_min]
    report(wet, f"전체 (비 {a.rain_min:.0f}mm 이상)", out)
    report(wet[wet.unseen == 1], "학습에 안 쓴 날만", out)
    for th in (20, 40):
        report(res[res.rain >= th], f"비 {th}mm 이상", out)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    res.to_csv(a.out.with_suffix(".csv"), index=False)
    print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
