#!/usr/bin/env python3
"""돌고 있는 우리 작업을 스스로 찾아 한 화면에 보여준다.

전에는 작업 목록을 손으로 적어 두었더니 새 작업을 돌릴 때마다 낡았다. 이제는
돌고 있는 파이썬 프로세스를 찾아, 그것이 쓰고 있는 로그 파일을 lsof 로 알아내고,
로그 모양에서 진행률을 읽는다. 새 스크립트를 만들어도 손댈 것이 없다.

로그 모양은 네 가지뿐이다.
  묶음 3/6            검증류
  20140818: 칸 ...    링 센서스 (사건마다 한 줄)
  40/174  (25분)      날짜를 훑는 채점
  [완료] 20230608     레이더 수집
"""
from __future__ import annotations
import argparse, os, re, subprocess, time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATS = [
    # '묶음 3/6' 은 진행이지만 '이긴 묶음 0/5' 는 결과다. 앞에 '이긴' 이 붙으면 거른다.
    ("fold",   re.compile(r"(?<!이긴 )묶음 (\d+)\s*/\s*(\d+)")),
    # 훑기: '둘레12' 나 '무작위7' 처럼 번호가 붙은 시도
    ("try",    re.compile(r"^\s*[↑\s]\s*(?:둘레|무작위)(\d+)\s")),
    ("census", re.compile(r"^(\d{8}): 칸")),
    ("day",    re.compile(r"^\s*(\d+)/(\d+)\s+\((\d+)분\)")),
    ("radar",  re.compile(r"^\[완료\] (\d{8})")),
]


def running():
    """우리 저장소의 스크립트를 돌리고 있는 프로세스와 그 로그를 찾는다."""
    out = subprocess.run(["ps", "-eo", "pid=,etime=,command="],
                         capture_output=True, text=True).stdout
    jobs = []
    for ln in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(\S+)\s+(.*)", ln)
        if not m:
            continue
        pid, et, cmd = m.groups()
        mm = re.search(r"scripts/(\w+)\.py", cmd)
        if not mm or "watch_eval" in cmd or cmd.lstrip().startswith("/bin/"):
            continue
        log = None
        try:
            lf = subprocess.run(["lsof", "-p", pid, "-a", "-d", "1", "-Fn"],
                                capture_output=True, text=True, timeout=4).stdout
            for l in lf.splitlines():
                if l.startswith("n/") and l.endswith(".log"):
                    log = l[1:]
        except Exception:
            pass
        jobs.append({"pid": pid, "name": mm.group(1), "et": et, "log": log})
    return jobs


def secs(et):
    s = 0
    for v in re.split("[:-]", et):
        if v.isdigit():
            s = s * 60 + int(v)
    return s


def progress(log):
    """로그에서 진행률과 남은 시간을 읽는다."""
    if not log or not Path(log).exists():
        return None, None, ""
    lines = Path(log).read_text(errors="replace").splitlines()
    for kind, pat in PATS:
        hits = [pat.search(l) for l in lines]
        hits = [h for h in hits if h]
        if not hits:
            continue
        if kind == "fold":
            done = len(hits); tot = int(hits[-1].group(2))
            # 조건이 여럿이면 묶음이 여러 바퀴 돈다
            tot = max(tot, done)
            return done, tot, ""
        if kind == "try":
            done = max(int(h.group(1)) for h in hits)
            # 훑기가 끝나고 확인으로 넘어갔으면 그렇게 알린다
            if any("[확인]" in l for l in lines):
                nconf = sum(1 for l in lines if re.search(r"이긴 묶음 \d+/\d+", l))
                return None, None, f"훑기 {done}가지 끝, 확인 {nconf}/3"
            return done, None, "훑는 중"
        if kind == "census":
            return len(hits), None, ""
        if kind == "day":
            h = hits[-1]
            return int(h.group(1)), int(h.group(2)), h.group(3) + "분 경과"
        if kind == "radar":
            return len(hits), None, ""
    return None, None, (lines[-1].strip()[:46] if lines else "")


def bar(f, w=26):
    n = max(0, min(w, int(round(f * w))))
    return "█" * n + "·" * (w - n)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gap", type=float, default=3.0)
    a = ap.parse_args()
    while True:
        jobs = running()
        os.system("clear")
        print(f"\033[1m워터파크 — 돌고 있는 일\033[0m   {datetime.now():%m-%d %H:%M:%S}")
        print("─" * 76)
        if not jobs:
            print("  도는 작업이 없다.")
        for j in jobs:
            done, tot, note = progress(j["log"])
            el = secs(j["et"]) / 60
            head = f" \033[32m●\033[0m {j['name'][:26]:<26}"
            if done is None:
                print(f"{head} {'':28} {el:5.0f}분째  {note}")
            elif tot:
                left = (tot - done) * el / max(done, 1)
                end = datetime.now() + timedelta(minutes=left)
                print(f"{head} {bar(done/tot)} {done:>4}/{tot:<4} "
                      f"남은 {left:4.0f}분 · {end:%H:%M} 끝")
            else:
                print(f"{head} {'':28} {done:>4}개 완료  {el:5.0f}분째")
            if j["log"]:
                print(f"   {'':28} \033[90m{j['log']}\033[0m")
        print("\n" + "─" * 76)
        print("  Ctrl-C 로 나감 (작업은 계속 돈다)")
        time.sleep(a.gap)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
