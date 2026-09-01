#!/usr/bin/env python3
"""1단계가 고른 설정 둘레를 좁혀서 다시 훑는다.

첫 훑기는 넓게 흩뿌려 어느 축이 움직이는지 보는 것이었다. 이제 이긴 설정 둘레만
무작위로 마흔 번 본다. 넓게 한 번보다 좁혀서 두 번이 낫다 -- 첫 판에서 쓸모없다고
드러난 구석에 예산을 쓰지 않는다.

각 손잡이는 이긴 값의 0.6~1.7 배 범위에서 뽑는다. 정수 손잡이는 반올림한다.
고르는 데 쓴 묶음은 채점에서 뺀다.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_flood_map_national import MODEL_KW           # noqa: E402
from eval_hyper_sweep import prep, run                  # noqa: E402

INTS = {"n_estimators", "max_depth", "min_child_weight"}
BOUNDS = {"max_depth": (4, 18), "learning_rate": (0.01, 0.3), "subsample": (0.4, 1.0),
          "colsample_bytree": (0.3, 1.0), "reg_lambda": (0.05, 50.0),
          "min_child_weight": (1, 200), "n_estimators": (200, 5000)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", type=Path,
                    default=ROOT / "data/processed/ml/training/ring_census30_146.csv")
    ap.add_argument("--sweep", type=Path,
                    default=ROOT / "outputs/flooded-building-register/hyper_sweep.json")
    ap.add_argument("--sample", type=float, default=0.35)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--screen-fold", type=int, default=1)   # 1단계와 다른 묶음으로 고른다
    ap.add_argument("--random", type=int, default=40)
    ap.add_argument("--confirm", type=int, default=3)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "outputs/flooded-building-register/hyper_refine.json")
    a = ap.parse_args()

    best = dict(MODEL_KW)
    if a.sweep.exists():
        sw = json.loads(a.sweep.read_text(encoding="utf-8"))
        conf = sw.get("확인", {})
        won = [(v["top5"], k, v.get("kw")) for k, v in conf.items() if v.get("kw")]
        cur = conf.get("지금 설정", {}).get("top5", -1)
        won = [w for w in won if w[0] > cur]
        if won:
            best = max(won)[2]
            print(f"1단계가 고른 설정: {max(won)[1]}  (상위5% {max(won)[0]:.1f}%)")
    print("둘레를 훑을 중심:", {k: best[k] for k in sorted(best)}, "\n", flush=True)

    d = prep(a.table, a.sample, 6)
    rng = np.random.default_rng(1)
    t0 = time.time()
    base_auc, base_cap, _ = run(d, best, [a.screen_fold], a.jobs)
    print(f"[훑기] 묶음 {a.screen_fold} 로만.  중심 설정: 상위5% {base_cap:.1f}%\n", flush=True)

    rows = [{"이름": "중심", "kw": dict(best), "top5": base_cap}]
    for i in range(a.random):
        kw = {}
        for k, v in best.items():
            lo, hi = BOUNDS[k]
            nv = float(v) * float(rng.uniform(0.6, 1.7))
            nv = min(max(nv, lo), hi)
            kw[k] = int(round(nv)) if k in INTS else round(nv, 4)
        _, cap, _ = run(d, kw, [a.screen_fold], a.jobs)
        rows.append({"이름": f"둘레{i+1}", "kw": kw, "top5": cap})
        mark = "\033[32m↑\033[0m" if cap > base_cap else " "
        print(f"  {mark} 둘레{i+1:<3} 깊이{kw['max_depth']:>3} 나무{kw['n_estimators']:>5} "
              f"lr{kw['learning_rate']:<6} mcw{kw['min_child_weight']:<4} "
              f"sub{kw['subsample']:<5} col{kw['colsample_bytree']:<5} L2 {kw['reg_lambda']:<6} "
              f"상위5% {cap:5.1f}% ({cap-base_cap:+.1f}p) [{(time.time()-t0)/60:.0f}분]", flush=True)

    rows.sort(key=lambda r: -r["top5"])
    hold = [f for f in range(6) if f != a.screen_fold]
    print(f"\n[확인] 앞선 {a.confirm}개를 묶음 {hold} 로 (고르는 데 쓴 묶음은 뺀다)", flush=True)
    out = {}
    b_auc, b_cap, b_per = run(d, best, hold, a.jobs)
    out["중심"] = {"auc": b_auc, "top5": b_cap, "per": b_per, "kw": best}
    print(f"  중심            AUC {b_auc:.4f}  상위5% {b_cap:5.1f}%", flush=True)
    for r in [x for x in rows if x["이름"] != "중심"][:a.confirm]:
        auc, cap, per = run(d, r["kw"], hold, a.jobs)
        dd = np.array(per) - np.array(b_per); se = dd.std(ddof=1) / np.sqrt(len(dd))
        v = "낫다" if dd.mean() > 2*se else ("못하다" if dd.mean() < -2*se else "판정불가")
        out[r["이름"]] = {"auc": auc, "top5": cap, "per": per, "kw": r["kw"]}
        print(f"  {r['이름']:<14} AUC {auc:.4f}  상위5% {cap:5.1f}%   "
              f"{dd.mean():+.2f}p ± {se:.2f}  이긴 묶음 {int((dd>0).sum())}/{len(dd)}  -> {v}",
              flush=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"훑기": rows, "확인": out}, ensure_ascii=False,
                                indent=2, default=float), encoding="utf-8")
    print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
