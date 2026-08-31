#!/usr/bin/env python3
"""돌고 있는 채점·검증을 한 화면에서 본다.

로그마다 형식이 달라 tail 을 여러 개 띄워야 했다. 진행 형태가 둘뿐이므로
(하루씩 세는 것, 묶음씩 세는 것) 둘 다 읽어 남은 시간까지 계산한다.
"""
from __future__ import annotations
import argparse, os, re, time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# (이름, 로그, 진행 정규식, 전체 개수를 읽는 정규식 또는 고정값, 프로세스 이름)
JOBS = [
    ("88개 폭풍 표", "/tmp/census88.log", r"^(\d{8}): 칸", 88, "build_ring_census30"),
    ("2023 레이더", "/tmp/radar2023.log", None, 7, "events_2023_missing"),
    ("읍면동 기사 채점", "/tmp/emdeval.log", r"^\s*(\d+)/(\d+)\s+\((\d+)분\)", None,
     "eval_against_news_emd"),
    ("시군구 기사 채점", "/tmp/newseval2.log", r"^\s*(\d+)/(\d+)\s+\((\d+)분\)", None,
     "eval_against_news.py"),
    ("비 시간모양 검증", "/tmp/shapeeval.log", r"묶음 (\d+)/?\d*", 12, "eval_rain_shape"),
    ("레이더 수집", "/tmp/news_radar.log", None, 43, "collect_radar_rainfall"),
]


def elapsed_min(proc):
    """그 프로세스가 몇 분째 돌고 있나."""
    out = os.popen(f"ps -o etime= -p $(pgrep -f {proc} | head -1) 2>/dev/null").read().strip()
    if not out:
        return 0.0
    sec = 0
    for v in re.split("[:-]", out):
        if v.isdigit():
            sec = sec * 60 + int(v)
    return sec / 60


def bar(f, w=30):
    n = max(0, min(w, int(round(f * w))))
    return "█" * n + "·" * (w - n)


def read(job):
    name, log, pat, tot, proc = job
    p = Path(log)
    alive = os.system(f"pgrep -f {proc} > /dev/null 2>&1") == 0
    if not p.exists():
        return name, None, None, alive, "로그 없음"
    lines = p.read_text(errors="replace").splitlines()
    if proc == "collect_radar_rainfall":
        done = sum(1 for l in lines if l.startswith("[완료]"))
        cur = next((l.strip() for l in reversed(lines) if re.match(r"^\s+\d{8}\s+\d+/", l)), "")
        return name, done, tot, alive, cur[:52]
    done = mins = None
    for l in reversed(lines):
        m = re.search(pat, l)
        if m:
            done = int(m.group(1))
            if m.lastindex and m.lastindex >= 2 and m.group(2).isdigit():
                tot = int(m.group(2))
            if m.lastindex and m.lastindex >= 3:
                mins = int(m.group(3))
            break
    if done is None:
        last = lines[-1].strip() if lines else ""
        return name, None, tot, alive, last[:52]
    # 묶음식 로그는 완료 줄을 세는 편이 정확하다
    if proc == "eval_rain_shape":
        done = sum(1 for l in lines if re.search(r"묶음 \d+ .*AUC", l))
    if proc == "build_ring_census30":
        # 사건마다 한 줄씩 쌓인다. 시각이 없으므로 파일 나이로 속도를 잰다
        done = sum(1 for l in lines if re.match(r"^\d{8}: 칸", l))
        # 파일의 ctime 은 덧붙일 때마다 갱신되어 쓸 수 없다. 프로세스 나이를 쓴다.
        el = elapsed_min(proc)
        if done and done < tot:
            left = (tot - done) * el / done
            return name, done, tot, alive, (f"남은 {left:.0f}분 · "
                                            f"{datetime.now()+timedelta(minutes=left):%H:%M} 끝")
        return name, done, tot, alive, "완료" if done >= tot else ""
    eta = ""
    if mins and done:
        left = (tot - done) * mins / done
        eta = f"남은 {left:.0f}분 · {datetime.now()+timedelta(minutes=left):%H:%M} 끝"
    return name, done, tot, alive, eta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gap", type=float, default=3.0)
    a = ap.parse_args()
    while True:
        os.system("clear")
        print(f"\033[1m워터파크 — 돌고 있는 일\033[0m   {datetime.now():%m-%d %H:%M:%S}")
        print("─" * 72)
        any_alive = False
        for job in JOBS:
            name, done, tot, alive, note = read(job)
            any_alive |= alive
            state = "\033[32m●\033[0m" if alive else "\033[90m○\033[0m"
            if done is None:
                print(f" {state} {name:<16} {'':32}  {note}")
            else:
                f = done / max(tot or 1, 1)
                print(f" {state} {name:<16} {bar(f)} {done:>4}/{tot or '?':<4} {note}")
        print("\n" + "─" * 72)
        if not any_alive:
            print(" 모두 끝났다. Ctrl-C 로 나감.")
        else:
            print(" ● 도는 중   ○ 멈춤        Ctrl-C 로 나감 (작업은 계속 돈다)")
        time.sleep(a.gap)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
