#!/usr/bin/env python3
"""레이더 수집 현황을 한 화면에 보여준다.

수집기는 로그에 한 줄씩 쌓기만 해서, 지금 어디까지 왔고 언제 끝나는지 보려면
사람이 tail 을 눈으로 따라가야 한다. 남은 사건 수와 최근 속도로 전체 예상
시각까지 계산해 한 화면에 묶는다.

대용량 서비스는 15:00~24:00 에만 열리므로 그 창이 얼마나 남았는지도 같이 띄운다.
"""
from __future__ import annotations
import argparse, json, os, re, time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROG = re.compile(r"^\s*(\d{8})\s+(\d+)/(\d+)\s+성공 (\d+)\s+(\d+)프레임/분\s+([\d.]+) MB/s")
DONE = re.compile(r"^\[완료\] (\d{8})\s+(\d+)/(\d+)프레임\s+(\d+)s")
START = re.compile(r"^\[시작\] (\d{8})")
SAVE = re.compile(r"^\[격자 저장\] (\d{8})\s+([\d.]+)MB")


def read(log: Path):
    try:
        lines = log.read_text(errors="replace").splitlines()
    except FileNotFoundError:
        return None
    st = {"cur": None, "done": [], "secs": [], "mb": [], "last": None, "started": []}
    for ln in lines:
        m = START.match(ln)
        if m:
            st["started"].append(m.group(1)); st["cur"] = m.group(1); st["last"] = None
        m = PROG.match(ln)
        if m:
            st["last"] = dict(ev=m.group(1), got=int(m.group(2)), tot=int(m.group(3)),
                              ok=int(m.group(4)), fpm=int(m.group(5)), mbs=float(m.group(6)))
        m = DONE.match(ln)
        if m:
            st["done"].append(m.group(1)); st["secs"].append(int(m.group(4)))
        m = SAVE.match(ln)
        if m:
            st["mb"].append(float(m.group(2)))
    return st


def bar(frac, width=34):
    n = max(0, min(width, int(round(frac * width))))
    return "█" * n + "·" * (width - n)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log", type=Path, default=Path("/tmp/news_radar.log"))
    ap.add_argument("--events", type=Path, default=ROOT / "config/radar/events_from_news.json")
    ap.add_argument("--gap", type=float, default=2.0)
    a = ap.parse_args()
    try:
        target = json.loads(a.events.read_text())
    except Exception:
        target = []

    while True:
        st = read(a.log)
        os.system("clear")
        now = datetime.now()
        print(f"\033[1m레이더 수집\033[0m   {now:%m-%d %H:%M:%S}   로그 {a.log}")
        print("─" * 62)
        if st is None:
            print("  로그가 아직 없다."); time.sleep(a.gap); continue

        alive = os.system("pgrep -f collect_radar_rainfall > /dev/null 2>&1") == 0
        done = len(st["done"]); tot = len(target) or (done + 1)
        print(f"  사건   {bar(done/tot)}  {done}/{tot}   "
              + ("\033[32m돌는 중\033[0m" if alive else "\033[31m멈춤\033[0m"))

        L = st["last"]
        if L and st["cur"] and L["ev"] == st["cur"]:
            f = L["got"] / max(L["tot"], 1)
            fail = L["got"] - L["ok"]
            print(f"  현재   {bar(f)}  {L['ev']}  {L['got']}/{L['tot']}프레임"
                  + (f"  \033[31m실패 {fail}\033[0m" if fail else ""))
            print(f"\n  속도   \033[1m{L['mbs']:.1f} MB/s\033[0m   {L['fpm']}프레임/분")
            left_f = L["tot"] - L["got"]
            eta_cur = left_f / max(L["fpm"], 1)
            print(f"  이 사건 남은 시간  약 {eta_cur:.0f}분")
        else:
            print(f"  현재   {st['cur'] or '-'}  (준비 중)")
            eta_cur = 0

        if st["secs"]:
            avg = sum(st["secs"][-5:]) / len(st["secs"][-5:])
            rest = (tot - done - 1) * avg / 60 + eta_cur
            end = now + timedelta(minutes=rest)
            print(f"\n  사건당 평균 {avg/60:.1f}분   남은 {tot-done}개")
            print(f"  \033[1m전체 예상 종료  {end:%m-%d %H:%M}  (약 {rest/60:.1f}시간 뒤)\033[0m")
        if st["mb"]:
            print(f"  받은 용량  {sum(st['mb'])/1024:.1f} GB   "
                  f"사건당 평균 {sum(st['mb'])/len(st['mb']):.0f} MB")

        # 대용량 서비스 창 (15:00~24:00)
        if 15 <= now.hour < 24:
            close = now.replace(hour=23, minute=59, second=59)
            print(f"\n  \033[33m대용량 서비스 열림 — 마감까지 "
                  f"{int((close-now).total_seconds()//60)}분\033[0m")
        else:
            nxt = (now.replace(hour=15, minute=0, second=0)
                   + timedelta(days=1 if now.hour >= 15 else 0))
            print(f"\n  \033[33m대용량 서비스 닫힘 — {nxt:%H:%M} 에 열림 "
                  f"({int((nxt-now).total_seconds()//60)}분 뒤)\033[0m")
        print("\n  Ctrl-C 로 나감 (수집은 계속 돈다)")
        time.sleep(a.gap)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
