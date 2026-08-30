#!/usr/bin/env python3
"""기사로 채점한다. 우리 라벨과 출처가 다른, 두 번째 시험지.

지금까지 채점은 침수 폴리곤으로만 했다. 그 폴리곤은 학습 라벨과 같은 조사에서
나온 것이라, "조사가 이뤄진 곳에서만 라벨이 온다"는 문제를 채점이 잡아내지
못한다. 기사는 완전히 다른 경로로 만들어진 기록이다.

라벨을 30 m 로 내리는 것은 불가능하지만 (시군구 하나가 10 만 칸이다) 우리
예측을 시군구로 올리는 것은 손실이 없다.

이 채점을 설계하면서 걸러야 했던 것들:

1. \033[1m강수 교란\033[0m -- 비가 많이 온 곳에 기사가 나는 것은 당연하다. 그냥 맞히면
   "강수량만 출력하는 모델"과 구별이 안 된다. 그래서 강수만 쓰는 기준선과
   반드시 나란히 놓고, 우리가 그것을 넘는지를 본다. 이것이 이 채점의 핵심이다.
2. \033[1m도시 교란\033[0m -- 사람이 많은 곳에 기사가 난다. 우리 모델은 불투수율을 보고
   도시를 위험하다고 한다. 그래서 시가지 비율만 쓰는 기준선도 같이 놓는다.
3. \033[1m면적 편향\033[0m -- 시군구 안 최댓값은 넓은 곳일수록 커진다. 시군구마다 같은
   수의 칸을 뽑고, 대표값은 표본 수에 무관한 분위수를 쓴다.
4. \033[1m기사 날짜\033[0m -- 새벽 침수는 이튿날 기사가 된다. 하루 뒤까지 인정한다.
5. \033[1m회고 기사\033[0m -- 옛 침수를 오늘 보도한 것이 2% 있다. 그날 그 시군구에 비가
   왔을 것을 요구하면 대부분 걸러진다.
6. \033[1m학습에 쓴 날\033[0m -- 따로 떼어 다시 낸다.

한계는 그대로 남는다. 기사가 없다고 침수가 없었던 것은 아니고, 작은 침수는
기사가 되지 않는다. 그 오류는 우리에게 불리한 쪽이므로 여기 점수는 실제보다
낮게 나온다. 기사는 하천 범람과 내수 침수를 구분하지도 않는다.
"""
from __future__ import annotations
import argparse, ast, json, sys, time
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


def load(name, path):
    import importlib.util
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    return m


def article_bags(alias, keys):
    """(날짜, 시군구) -> 기사 수. 새벽 침수는 이튿날 기사가 되므로 하루 뒤까지 센다."""
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
    # 이름이 하나뿐인 시군구는 시도를 묻지 않고 붙이고, '동구'처럼 여러 시도에
    # 있는 이름만 시도로 가른다. 모든 조합을 곱하면 없는 짝이 생긴다.
    by_name: dict[str, list] = {}
    for k in keys:
        by_name.setdefault(k.split("|")[-1], []).append(k)
    rows = []
    for d0, sd, sg in zip(a.d, a.SIDO_CLSF, a.SGG_CLSF):
        want = {alias.get(x, x) for x in lst(sd)}
        for s in lst(sg):
            cand = by_name.get(s, [])
            hit = cand if len(cand) == 1 else [c for c in cand if c.split("|")[0] in want]
            for c in hit:
                rows.append((d0.strftime("%Y%m%d"), c))
                rows.append(((d0 - pd.Timedelta(days=1)).strftime("%Y%m%d"), c))
    b = pd.DataFrame(rows, columns=["day", "key"])
    return b.groupby(["day", "key"]).size().rename("articles").reset_index()


def report(s, label, out):
    """우리 예측과 기준선들을 같은 자료 위에 나란히 놓는다."""
    if len(s) < 200 or s.hit.nunique() < 2:
        print(f"\n[{label}] 표본이 모자라 건너뜀 ({len(s)}개)"); return
    base = float(s.hit.mean())
    k = max(int(len(s) * 0.05), 1)
    print(f"\n\033[1m[{label}]\033[0m 덩어리 {len(s):,}개, 기사 난 것 {base*100:.1f}%")
    print(f"  {'무엇으로 순위를 매겼나':<24}{'AUC':>8}{'상위5% 적중':>12}{'기저대비':>9}")
    got = {}
    for name, col in (("우리 모델 (평균확률)", "pmean"),
                      ("우리 모델 (5% 넘는 칸 비율)", "f05"),
                      ("우리 모델 (10% 넘는 칸 비율)", "f10"),
                      ("우리 모델 (p99)", "p99"), ("우리 모델 (최댓값)", "pmax"),
                      ("── 강수량만 (최대)", "rain"), ("── 강수량만 (평균)", "rain_mean"),
                      ("── 시가지 비율만", "built")):
        if col not in s or s[col].nunique() < 2:
            continue
        auc = roc_auc_score(s.hit, s[col])
        top = s.nlargest(k, col).hit.mean()
        got[col] = {"auc": float(auc), "top5": float(top), "lift": float(top / max(base, 1e-9))}
        print(f"  {name:<24}{auc:8.4f}{top*100:11.1f}%{top/max(base,1e-9):8.1f}배")
    if "f05" in got and "rain" in got:
        d = got["f05"]["auc"] - got["rain"]["auc"]
        print(f"\n  \033[1m우리 - 강수량만 = AUC {d:+.4f}\033[0m"
              f"   {'우리가 낫다' if d > 0.01 else '강수량과 구별 안 됨' if abs(d) <= 0.01 else '강수량만도 못하다'}")
    out[label] = {"덩어리": int(len(s)), "기사난비율": base, "지표": got}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_all_full.csv")
    ap.add_argument("--per-sgg", type=int, default=20_000)
    ap.add_argument("--rain-min", type=float, default=10.0)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "outputs/flooded-building-register/news_eval.json")
    a = ap.parse_args()

    idx = json.loads((G30 / "sgg_index.json").read_text(encoding="utf-8"))
    alias, name_of = idx["alias"], {v: k for k, v in idx["index"].items()}
    bags = article_bags(alias, list(idx["index"]))
    print(f"기사 덩어리 {len(bags):,}개  ({bags.day.nunique()}일, {bags.key.nunique()}개 시군구)")

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
    sgg = np.load(G30 / "sgg_id.npy", mmap_mode="r")
    el = np.load(G30 / "elevation.npy", mmap_mode="r")
    step = 4
    sub = np.asarray(sgg[::step, ::step])
    sube = np.asarray(el[::step, ::step], dtype="float32")
    ok = (sub > 0) & np.isfinite(sube) & (sube > 0)
    ids, rr, cc = sub[ok], *(x * step for x in np.nonzero(ok))
    order = np.argsort(ids, kind="stable")
    ids, rr, cc = ids[order], rr[order], cc[order]
    uniq, starts = np.unique(ids, return_index=True)
    edges = list(starts) + [len(ids)]
    rng = np.random.default_rng(0)
    sel = np.concatenate([rng.choice(np.arange(edges[i], edges[i + 1]),
                                     min(a.per_sgg, edges[i + 1] - edges[i]), replace=False)
                          for i in range(len(uniq))])
    allr, allc, owner = rr[sel], cc[sel], ids[sel]
    print(f"시군구 {len(uniq)}개, 표본 {len(sel):,}칸 "
          f"(시군구당 중앙값 {int(np.median(np.bincount(owner)[np.bincount(owner) > 0])):,})", flush=True)

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
    near = ridx[cKDTree(np.c_[rlon[good] * 88_000, rlat[good] * 111_000])
                .query(np.c_[lon * 88_000, lat * 111_000], k=1)[1]]

    rows, t0 = [], time.time()
    files = sorted((RAD / "grids_full").glob("rain_*_grid.npz"))
    for n, f in enumerate(files):
        ev = f.stem.replace("rain_", "").replace("_grid", "")
        z = np.load(f)
        spans = z["span_min"].astype("float64")
        series = rate_fn(z["grid"].astype("float32") / 100.0).reshape(len(spans), -1)
        tot = bett.accumulate(series, spans, forward=False)
        del series
        rain = tot[6][near]
        X[:, i6] = np.minimum(rain, PLATEAU_MM)
        X[:, i1] = X[:, i6] * RATIO_1H_6H
        p = m.predict_proba(X)[:, 1]
        odds = p / np.maximum(1 - p, 1e-9) / w
        p = odds / (1 + odds)
        df = pd.DataFrame({"sgg": owner, "p": p, "rain": rain, "built": built})
        # 분위수와 최댓값은 시군구마다 거의 상수라 날씨 정보를 통째로 잃는다.
        # (p99 는 같은 시군구 안에서 날이 바뀌어도 표준편차가 0.0003 이었다.)
        # 기사가 날 만한 일이 벌어지려면 위험한 칸이 '많아야' 하므로, 넓이에
        # 비례하는 값 -- 평균 확률과 문턱 넘은 칸의 비율 -- 을 같이 낸다.
        agg = df.groupby("sgg").agg(pmax=("p", "max"), p99=("p", lambda s: np.quantile(s, .99)),
                                    pmean=("p", "mean"),
                                    f05=("p", lambda s: float((s > 0.05).mean())),
                                    f10=("p", lambda s: float((s > 0.10).mean())),
                                    rain=("rain", "max"), rain_mean=("rain", "mean"),
                                    built=("built", "mean"), n=("p", "size")).reset_index()
        agg["day"] = ev
        agg["key"] = [name_of.get(int(i), "") for i in agg.sgg]
        rows.append(agg)
        if (n + 1) % 10 == 0 or n == len(files) - 1:
            print(f"  {n+1}/{len(files)}  ({(time.time()-t0)/60:.0f}분)", flush=True)
    res = pd.concat(rows)
    res = res.merge(bags, on=["day", "key"], how="left")
    res["hit"] = res.articles.notna().astype(int)
    res["unseen"] = (~res.day.isin(train_days)).astype(int)

    out = {}
    wet = res[res.rain >= a.rain_min]
    report(wet, f"전체 (비 {a.rain_min:.0f}mm 이상)", out)
    report(wet[wet.unseen == 1], f"학습에 안 쓴 날만", out)
    print("\n=== 비 기준을 바꿔가며 (결과가 기준에 흔들리는지) ===")
    for th in (5, 20, 40):
        report(res[res.rain >= th], f"비 {th}mm 이상", out)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    res.to_csv(a.out.with_suffix(".csv"), index=False)
    print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
