#!/usr/bin/env python3
"""When did the water actually arrive? Check the recorded hour against the rain.

Accumulations have to end when the flood happened; rain that fell afterwards
cannot have caused it. The recorded hour comes from the trace survey and is
usually right, but it was wrong twice in a sample of sixteen, and a wrong hour
mixes post-flood rain into the window and destroys the signal.

With 48 hours of frames the record can be tested. For each candidate cut-off
the six hours before it are accumulated, and the hour where the flood points
stand furthest above the controls is the one the rain points to.

Picking the hour that maximises that gap is fitting to the outcome, so it is
not trusted on its own. It is first run on events whose hour is known: if it
recovers those, the method is sound and can be believed where the hour is
missing. Where a recorded hour exists it is kept unless the rain disagrees by
more than `--tolerance` hours AND the recorded hour has almost no rain behind
it -- the signature of the two errors already found.
"""
from __future__ import annotations
import argparse, importlib.util, json
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bett", ROOT / "scripts/build_event_training_table.py")
bett = importlib.util.module_from_spec(spec); spec.loader.exec_module(bett)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--radar-dir", type=Path, default=ROOT / "data/interim/radar/events_full")
    p.add_argument("--points", type=Path, required=True)
    p.add_argument("--recorded", type=Path, required=True)
    p.add_argument("--tolerance", type=int, default=3)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()

    pts = pd.read_csv(a.points, dtype={"event": str}); pts["event"] = pts.event.fillna("")
    recorded = {k: int(v) for k, v in json.loads(a.recorded.read_text(encoding="utf-8")).items()}

    rows = []
    for path in sorted(a.radar_dir.glob("rain_*.npz")):
        ev = path.stem.replace("rain_", "")
        z = np.load(path)
        n = z["series"].shape[1]
        fm = ((pts.kind == "flood") & (pts.event == ev)).to_numpy()[:n]
        cm = (pts.kind == "control").to_numpy()[:n]
        if fm.sum() < 20:
            continue
        stamps = [str(s) for s in z["stamps"]]
        spans = z["span_min"].astype(float)
        best = None
        for cut in range(36, len(stamps) + 1):          # 최소 6시간치는 남기고
            t = bett.accumulate(z["series"][:cut], spans[:cut], forward=False)
            gap = float(np.nanmedian(t[6][fm]) - np.nanmedian(t[6][cm]))
            if best is None or gap > best[0]:
                best = (gap, stamps[cut - 1], float(np.nanmedian(t[6][fm])))
        gap, stamp, fr = best
        # 그 사건일 기준 시각으로 환산 (다음날이면 24를 더한다)
        day = int(stamp[6:8]) - int(ev[6:8])
        hour = int(stamp[8:10]) + 24 * day + (1 if int(stamp[10:12]) > 0 else 0)
        rows.append({"event": ev, "flood_pts": int(fm.sum()), "rain_hour": hour,
                     "gap_mm": round(gap, 1), "flood_rain_mm": round(fr, 1),
                     "recorded": recorded.get(ev)})

    d = pd.DataFrame(rows)
    known = d[d.recorded.notna()].copy()
    known["diff"] = (known.rain_hour - known.recorded).abs()
    print(f"사건 {len(d)}개 (침수점 20건 이상), 그중 기록된 시각이 있는 것 {len(known)}개\n")
    print("=== 검증: 비가 가리키는 시각이 기록된 시각과 얼마나 맞나 ===")
    for t in (0, 1, 2, 3, 6):
        print(f"  {t}시간 이내 일치: {(known['diff'] <= t).sum():3d}/{len(known)} "
              f"({(known['diff'] <= t).mean()*100:.0f}%)")
    print(f"  중앙 오차 {known['diff'].median():.1f}시간")

    print("\n=== 크게 어긋나는 사건 (기록 시각에 비가 거의 없음) ===")
    bad = known[(known["diff"] > a.tolerance) & (known.flood_rain_mm > 10)]
    print(f"  {len(bad)}개")
    for _, r in bad.sort_values("gap_mm", ascending=False).head(12).iterrows():
        print(f"    {r.event}  기록 {int(r.recorded):2d}시 -> 비가 가리키는 {int(r.rain_hour):3d}시  "
              f"침수점 강수 {r.flood_rain_mm:6.1f}mm  대조와 차이 {r.gap_mm:6.1f}mm  "
              f"(침수점 {int(r.flood_pts):,})")

    d.to_csv(a.out, index=False)
    print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
