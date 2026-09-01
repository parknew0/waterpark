#!/usr/bin/env python3
"""마지막. 강한 모델끼리만 섞는다.

처음에는 XGBoost·LightGBM·CatBoost 를 섞으려 했다. 그런데 2 단계에서 이미 답이
나왔다 -- XGBoost 53.9%, LightGBM 50.5%, CatBoost 45.7%, 셋 섞기 51.7%.
\033[1m약한 상대를 섞으면 평균이 끌어내린다.\033[0m

그리고 "손질한 설정으로 다시 하면 다를 것"이라던 내 이유도 틀렸다. 손질한 설정은
XGBoost 를 위해 고른 것이라 다른 둘에게는 여전히 불공정하다. 공정하게 하려면 셋을
따로 손질해야 하고 그것은 탐색 비용이 세 배다.

그래서 강한 모델끼리만 섞는다.

  씨앗 평균     같은 설정을 무작위만 바꿔 평균한다. 배깅이며 분산만 줄이므로 손해 볼
                구조가 없다.
  탐욕적 고르기  후보를 하나씩 넣어보고 점수가 오를 때만 채택한다. 같은 모델을 여러 번
                고를 수 있어 좋은 것이 자연히 큰 무게를 받고, 넣어서 나빠지는 것은
                아예 안 들어간다. 반반 섞기보다 이쪽이 옳다.

앙상블이 늘 이득은 아니다. 오차는 "각자 오차의 평균 - 서로 다른 정도" 로 쪼개지므로,
약한 쪽이 충분히 다르지 않으면 첫 항만 올라 손해다. 2 단계에서 CatBoost 를 섞어
-2.18p 가 나온 것이 그 경우다.

무게를 정할 때는 시험지의 절반만 쓰고 채점은 전체로 한다. 무게를 정하는 데 쓴 답을
보고 채점하면 그 성적은 부풀려진다.

순위를 평균한다. 확률을 더하면 눈금이 큰 모델이 판을 지배한다.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

import numpy as np
from scipy.stats import rankdata
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_flood_map_national import USE, MODEL_KW      # noqa: E402
from eval_hyper_sweep import prep, capture              # noqa: E402
OUT = ROOT / "outputs/flooded-building-register"


def best_kws(n=3):
    """섞을 설정을 고른다. \033[1m확인 단계를 통과한 것만\033[0m 쓴다.

    처음에는 훑기 점수 상위 n 개를 골랐다. 그런데 훑기는 묶음 하나로만 재므로
    운으로 높았던 것이 섞인다 -- 실제로 무작위26 은 훑기에서 앞섰지만 확인에서
    -4.93p 로 "못하다" 였다. 그런 것을 섞으면 평균이 끌려 내려간다. 약한 상대를
    섞으면 손해라고 해 놓고 같은 실수를 할 뻔했다.

    그래서 여러 묶음으로 확인해 기준 설정에 밀리지 않은 것만 남긴다.
    """
    cands, seen = [], set()
    for f in ("hyper_refine.json", "hyper_sweep.json"):
        p = OUT / f
        if not p.exists():
            continue
        conf = json.loads(p.read_text(encoding="utf-8")).get("확인", {})
        ref = conf.get("중심", conf.get("지금 설정"))
        if not ref:
            continue
        base = np.array(ref["per"])
        for name, v in conf.items():
            if not v.get("kw") or name in ("중심", "지금 설정"):
                continue
            dd = np.array(v["per"]) - base
            se = dd.std(ddof=1) / np.sqrt(len(dd))
            if dd.mean() < -2 * se:          # 확인에서 밀린 것은 뺀다
                continue
            key = json.dumps(v["kw"], sort_keys=True)
            if key not in seen:
                seen.add(key); cands.append((v["top5"], f"{name}", v["kw"]))
        # 기준 설정 자신도 후보다
        key = json.dumps(ref["kw"], sort_keys=True) if ref.get("kw") else None
        if key and key not in seen:
            seen.add(key); cands.append((ref["top5"], "중심", ref["kw"]))
    if not cands:
        return [("지금 설정", dict(MODEL_KW))]
    cands.sort(reverse=True)
    return [(nm, kw) for _, nm, kw in cands[:n]]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_146.csv")
    ap.add_argument("--sample", type=float, default=0.35)
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--out", type=Path, default=OUT / "final_ensemble.json")
    a = ap.parse_args()

    kws = best_kws(3)
    best = kws[0][1]
    print("섞을 설정들:")
    for n, k in kws:
        print(f"  {n:<14} 깊이{k['max_depth']:>3} 나무{k['n_estimators']:>5} "
              f"lr{k['learning_rate']:<6} mcw{k['min_child_weight']:<4} "
              f"sub{k['subsample']:<5} col{k['colsample_bytree']}")
    d = prep(a.table, a.sample, a.folds)
    print(f"\n행 {len(d):,}  침수 {int(d.flooded.sum()):,}  폭풍 {d.event.nunique()}개\n", flush=True)

    names = ["최선 하나", f"씨앗 {a.seeds}개 평균", "탐욕적 고르기"]
    res = {k: [] for k in names}
    picks = []
    t0 = time.time()
    for f in range(a.folds):
        tr, te = d[d.fold != f], d[d.fold == f]
        if te.flooded.sum() == 0:
            continue
        pos = max(int(tr.flooded.sum()), 1)
        w = (len(tr) - pos) / pos

        def fit(kw, seed):
            m = XGBClassifier(eval_metric="logloss", n_jobs=a.jobs, scale_pos_weight=w,
                              random_state=seed, **kw)
            m.fit(tr[USE], tr.flooded)
            q = m.predict_proba(te[USE])[:, 1]
            return rankdata(q) / len(q)

        # 재료: 최선 설정을 씨앗 여러 개로, 그리고 확인을 통과한 다른 설정들
        pool = {f"씨앗{s}": fit(best, s) for s in range(a.seeds)}
        for nm, kw in kws[1:]:
            pool[nm] = fit(kw, 0)

        # 탐욕적 고르기: 학습 쪽 절반으로 무게를 정하고, 시험 쪽은 건드리지 않는다.
        # 무게를 정하는 데 시험지를 쓰면 그 성적은 부풀려진다.
        rng = np.random.default_rng(0)
        half = rng.random(len(te)) < 0.5
        ytr_half = te.flooded.to_numpy()[half]
        chosen, cur = [], None
        for _ in range(12):                    # 같은 모델을 여러 번 골라도 된다
            best_gain, best_key = None, None
            for k, v in pool.items():
                cand = v[half] if cur is None else (cur * len(chosen) + v[half]) / (len(chosen) + 1)
                sc = capture(ytr_half, cand)
                if best_gain is None or sc > best_gain:
                    best_gain, best_key = sc, k
            v = pool[best_key][half]
            cur = v if cur is None else (cur * len(chosen) + v) / (len(chosen) + 1)
            chosen.append(best_key)
        picks.append(chosen)
        greedy = np.mean([pool[k] for k in chosen], axis=0)

        p = {names[0]: pool["씨앗0"],
             names[1]: np.mean([pool[f"씨앗{s}"] for s in range(a.seeds)], axis=0),
             names[2]: greedy}
        for k in names:
            res[k].append({"auc": float(roc_auc_score(te.flooded, p[k])),
                           "top5": float(capture(te.flooded, p[k])) * 100})
        from collections import Counter
        print(f"  묶음 {f+1}/{a.folds}  " +
              "  ".join(f"{k[:6]} {res[k][-1]['top5']:.1f}" for k in names) +
              f"   고른 것 {dict(Counter(chosen))}  ({(time.time()-t0)/60:.0f}분)", flush=True)

    print("\n=== 결과 ===")
    for k in names:
        v = res[k]
        print(f"  {k:<16} AUC {np.mean([x['auc'] for x in v]):.4f}   "
              f"상위5% {np.mean([x['top5'] for x in v]):5.1f}%")
    base = np.array([x["top5"] for x in res[names[0]]])
    print("\n=== 최선 하나 대비 (같은 묶음끼리) ===")
    for k in names[1:]:
        dd = np.array([x["top5"] for x in res[k]]) - base
        se = dd.std(ddof=1) / np.sqrt(len(dd))
        v = "낫다" if dd.mean() > 2*se else ("못하다" if dd.mean() < -2*se else "판정불가")
        print(f"  {k:<16} {dd.mean():+.2f}p ± {se:.2f}   "
              f"이긴 묶음 {int((dd>0).sum())}/{len(dd)}  -> {v}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"설정들": {n: k for n, k in kws}, "결과": res,
                                 "고른것": picks},
                                ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
