#!/usr/bin/env python3
"""모델 설정을 훑는다. 깊이 하나로 +5.8p 였는데 나머지는 손도 안 댔다.

전체 격자는 수백 가지라 며칠이 걸린다. 두 가지를 섞어 줄인다.

[1m하나씩 바꾸기[0m -- 지금 설정에서 손잡이 하나만 움직인다. 어느 손잡이가 움직이기라도
하는지 열다섯 번으로 안다. 다만 [1m설정끼리 얽히는 몫을 통째로 놓친다[0m. 특히
learning_rate 와 n_estimators 는 서로 묶여 있어서 -- 학습률을 낮추면 나무가 더 필요하다 --
하나씩 바꾸면 "학습률 0.03 에 나무 2500" 같은 조합은 시도조차 되지 않는다.

[1m무작위로 뽑기[0m -- 일곱 손잡이를 한꺼번에 무작위로 정해 서른 번 본다. 격자보다
같은 예산에서 낫다는 것이 알려져 있다. 격자는 손잡이 하나당 세 값만 보지만 무작위는
서른 가지 값을 보고, 정작 중요한 손잡이는 몇 개뿐이기 때문이다. 얽힘도 자연히 잡힌다.

훑을 때는 묶음 하나로만 재고, 앞선 몇 개만 나머지 묶음으로 확인한다. 묶음 하나의
점수는 42~78% 까지 흔들리므로 훑기의 결과는 후보를 고르는 데만 쓴다.

[1m확인에는 훑기에 쓴 묶음을 넣지 않는다.[0m 마흔다섯 가지 중 그 묶음에서 가장 높은 것을
고른 뒤 같은 묶음으로 다시 재면, 운으로 높았던 몫까지 성적에 얹힌다. 고르는 데 쓴
시험지는 채점에서 빼야 한다.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_flood_map_national import USE, MODEL_KW      # noqa: E402

# 손잡이마다 지금 값 양옆으로
GRID = {
    "learning_rate": [0.03, 0.08, 0.15],
    "min_child_weight": [1, 20, 50],
    "subsample": [0.6, 1.0],
    "colsample_bytree": [0.5, 1.0],
    "reg_lambda": [0.5, 10.0],
    "max_depth": [9, 13],
    "n_estimators": [600, 2000],
}


def capture(y, p, frac=0.05):
    k = max(int(round(len(p) * frac)), 1)
    return float(np.asarray(y)[np.argsort(-p)[:k]].sum()) / max(float(np.sum(y)), 1.0)


def prep(table, sample, folds, extra=()):
    cols = sorted({*USE, "event", "flooded", *extra})
    dt = {c: "float32" for c in cols if c not in ("event", "flooded")}
    dt.update({"event": str, "flooded": "int8"})
    d = pd.read_csv(table, usecols=cols, dtype=dt)
    if sample < 1.0:
        d = d.sample(frac=sample, random_state=0)
    sh = d[d.flooded == 1].groupby("event").rain_6h.apply(lambda s: (s < 1).mean())
    d = d[~d.event.isin(sh[sh >= 0.5].index)]
    d["sewer_density"] = d.sewer_density.fillna(d.sewer_density.median())
    d = d.dropna(subset=list(USE))
    ev = d.groupby("event").flooded.sum().sort_values(ascending=False)
    fold, load = {}, np.zeros(folds)
    for e, n in ev.items():
        i = int(np.argmin(load)); fold[e] = i; load[i] += n
    d["fold"] = d.event.map(fold)
    return d


def run(d, kw, folds, jobs):
    aucs, caps = [], []
    for f in folds:
        tr, te = d[d.fold != f], d[d.fold == f]
        if te.flooded.sum() == 0:
            continue
        pos = max(int(tr.flooded.sum()), 1)
        m = XGBClassifier(eval_metric="logloss", n_jobs=jobs,
                          scale_pos_weight=(len(tr) - pos) / pos, **kw)
        m.fit(tr[USE], tr.flooded)
        p = m.predict_proba(te[USE])[:, 1]
        aucs.append(roc_auc_score(te.flooded, p)); caps.append(capture(te.flooded, p) * 100)
    return float(np.mean(aucs)), float(np.mean(caps)), caps


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_146.csv")
    ap.add_argument("--sample", type=float, default=0.35)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--screen-fold", type=int, default=0)
    ap.add_argument("--confirm", type=int, default=4, help="여섯 묶음으로 확인할 후보 수")
    ap.add_argument("--random", type=int, default=30, help="무작위로 뽑아볼 조합 수")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "outputs/flooded-building-register/hyper_sweep.json")
    a = ap.parse_args()

    d = prep(a.table, a.sample, 6)
    print(f"행 {len(d):,}  침수 {int(d.flooded.sum()):,}  폭풍 {d.event.nunique()}개\n")

    t0 = time.time()
    base_auc, base_cap, _ = run(d, MODEL_KW, [a.screen_fold], a.jobs)
    print(f"[훑기] 묶음 {a.screen_fold} 로만 잰다.  지금 설정: 상위5% {base_cap:.1f}%\n", flush=True)
    rows = [{"이름": "지금 설정", "kw": dict(MODEL_KW), "top5": base_cap, "auc": base_auc}]
    for key, vals in GRID.items():
        for v in vals:
            kw = dict(MODEL_KW); kw[key] = v
            auc, cap, _ = run(d, kw, [a.screen_fold], a.jobs)
            rows.append({"이름": f"{key}={v}", "kw": kw, "top5": cap, "auc": auc})
            mark = "\033[32m↑\033[0m" if cap > base_cap else " "
            print(f"  {mark} {key:<18}{str(v):>7}   상위5% {cap:5.1f}%  "
                  f"({cap-base_cap:+.1f}p)  [{(time.time()-t0)/60:.0f}분]", flush=True)

    # 무작위 뽑기: 얽힘을 잡는다. learning_rate 와 n_estimators 는 함께 움직이게 한다.
    rng = np.random.default_rng(0)
    print(f"\n[무작위] 일곱 손잡이를 한꺼번에 {a.random}가지", flush=True)
    for i in range(a.random):
        lr = float(rng.choice([0.02, 0.03, 0.05, 0.08, 0.12, 0.2]))
        kw = dict(
            learning_rate=lr,
            # 학습률이 낮으면 나무가 더 필요하다. 둘을 함께 정한다.
            n_estimators=int(rng.choice([400, 800, 1200, 2000, 3000]) * (0.05 / lr) ** 0.5),
            max_depth=int(rng.integers(6, 15)),
            min_child_weight=int(rng.choice([1, 3, 5, 10, 30, 80])),
            subsample=float(rng.choice([0.5, 0.7, 0.8, 0.9, 1.0])),
            colsample_bytree=float(rng.choice([0.4, 0.6, 0.8, 1.0])),
            reg_lambda=float(rng.choice([0.1, 0.5, 2.0, 5.0, 20.0])),
        )
        kw["n_estimators"] = int(min(max(kw["n_estimators"], 200), 4000))
        auc, cap, _ = run(d, kw, [a.screen_fold], a.jobs)
        rows.append({"이름": f"무작위{i+1}", "kw": kw, "top5": cap, "auc": auc})
        mark = "\033[32m↑\033[0m" if cap > base_cap else " "
        print(f"  {mark} 무작위{i+1:<3} 깊이{kw['max_depth']:>3} 나무{kw['n_estimators']:>5} "
              f"lr{kw['learning_rate']:<5} mcw{kw['min_child_weight']:<3} "
              f"sub{kw['subsample']:<4} col{kw['colsample_bytree']:<4} "
              f"L2 {kw['reg_lambda']:<4}  상위5% {cap:5.1f}% ({cap-base_cap:+.1f}p)  "
              f"[{(time.time()-t0)/60:.0f}분]", flush=True)

    rows.sort(key=lambda r: -r["top5"])
    cands = [r for r in rows if r["이름"] != "지금 설정"][:a.confirm]
    print(f"\n[확인] 앞선 {len(cands)}개를 여섯 묶음으로 다시 잰다", flush=True)
    final = {}
    hold = [f for f in range(6) if f != a.screen_fold]   # 고르는 데 쓴 묶음은 뺀다
    print(f"       (묶음 {a.screen_fold} 는 고르는 데 썼으므로 채점에서 뺀다. "
          f"확인은 묶음 {hold} 로)", flush=True)
    b_auc, b_cap, b_per = run(d, MODEL_KW, hold, a.jobs)
    final["지금 설정"] = {"auc": b_auc, "top5": b_cap, "per": b_per}
    print(f"  지금 설정          AUC {b_auc:.4f}  상위5% {b_cap:5.1f}%", flush=True)
    for r in cands:
        auc, cap, per = run(d, r["kw"], hold, a.jobs)
        final[r["이름"]] = {"auc": auc, "top5": cap, "per": per, "kw": r["kw"]}
        dd = np.array(per) - np.array(b_per)
        se = dd.std(ddof=1) / np.sqrt(len(dd))
        v = "낫다" if dd.mean() > 2*se else ("못하다" if dd.mean() < -2*se else "판정불가")
        print(f"  {r['이름']:<18} AUC {auc:.4f}  상위5% {cap:5.1f}%   "
              f"{dd.mean():+.2f}p ± {se:.2f}  이긴 묶음 {int((dd>0).sum())}/{len(dd)}  -> {v}", flush=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"훑기": rows, "확인": final}, ensure_ascii=False, indent=2,
                                default=float), encoding="utf-8")
    print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
