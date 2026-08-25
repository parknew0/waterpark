#!/usr/bin/env python3
"""Rainfall at flood sites and controls, read from the 500 m radar composite.

The service currently reads rain from ~660 gauges, whose nearest neighbours sit
8 km apart. On 2022-08-08 the 90th percentile of the difference between one
gauge and its closest neighbour was 26.7 mm/h — wider than the 30 mm that
separates a 호우주의보 from a 호우경보. Interpolating between gauges therefore
decides the alert level by accident as often as by measurement.

The radar composite is 2305 x 2881 at 500 m. Only the values under the points
we care about are kept; the 13 MB grid behind each timestamp is read and
discarded, which is the difference between a few megabytes of output and a
hundred gigabytes of it.

HSR carries reflectivity, not depth, so each frame is converted with the
Marshall-Palmer relation and the frames are integrated over time. Against the
gauges on that same hour this reproduced r = +0.74.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
RADAR = ROOT / "data/interim/radar"
NX, NY = 2305, 2881
CELLS = NX * NY
BASE = "https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-rdr_cmp1_api"

OUT_OF_RANGE = -290.0   # dBZ; -300 marks outside radar coverage
NO_ECHO = -250.0        # dBZ; -250 marks a scanned cell with no rain


def rain_rate(dbz: np.ndarray) -> np.ndarray:
    """Marshall-Palmer: Z = 200 R^1.6, so R = (Z/200)^(1/1.6) in mm/h."""
    out = np.zeros(dbz.shape, dtype="float32")
    echo = dbz > NO_ECHO
    z = np.power(10.0, np.clip(dbz[echo], -30.0, 80.0) / 10.0)
    out[echo] = np.power(z / 200.0, 1.0 / 1.6)
    return out


class Pacer:
    """Keep a floor on the gap between request starts.

    The daily volume allowance is the hard limit, but spacing starts still
    avoids a burst of new connections when more than one worker is used.
    """

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next_at)
            self.next_at = start + self.min_interval
        delay = start - time.monotonic()
        if delay > 0:
            time.sleep(delay)


class KeyRing:
    """Hand out API keys, retiring one as soon as its daily quota is gone.

    The hub caps a key at 5 GB a day and does not say so politely: once the
    allowance is spent the connection is refused outright, so a run that has
    been working for an hour starts returning nothing and looks like a network
    fault. Retiring the key on that signal and moving to the next one keeps a
    long collection from silently filling its output with gaps.
    """

    def __init__(self, keys: list[str]):
        self.keys = [k for k in keys if k]
        self.index = 0
        self.lock = threading.Lock()
        self.spent: set[str] = set()
        self.consecutive_failures = 0

    def note_success(self) -> None:
        with self.lock:
            self.consecutive_failures = 0

    def note_connection_failure(self) -> None:
        with self.lock:
            self.consecutive_failures += 1

    def blocked(self, limit: int = 4) -> bool:
        """Many refused connections in a row means the host stopped answering."""
        with self.lock:
            return self.consecutive_failures >= limit

    def current(self) -> str | None:
        with self.lock:
            return self.keys[self.index] if self.index < len(self.keys) else None

    def retire(self, key: str) -> str | None:
        """Move past `key` if it is still the active one, and report the next."""
        with self.lock:
            if self.index < len(self.keys) and self.keys[self.index] == key:
                self.spent.add(key)
                self.index += 1
                remaining = len(self.keys) - self.index
                print(f"[키] 소진 -> 다음 키로 전환 (남은 키 {remaining}개)", flush=True)
            return self.keys[self.index] if self.index < len(self.keys) else None


def fetch(stamp: str, ring: "KeyRing", pacer: "Pacer", retries: int = 4) -> np.ndarray | None:
    """One frame, distinguishing a spent key from a blocked connection.

    These fail differently and the difference matters. A spent key still
    answers -- HTTP 200 carrying a JSON error, or a 403 -- and the right move
    is to switch keys. A blocked IP refuses the TCP connection outright, and
    switching keys does nothing because the block is not on the key; the only
    move is to wait. Treating the second as the first burned three good keys
    in a few seconds.
    """
    need = CELLS * 2
    loud = os.environ.get("RADAR_TRACE") == "1"
    for attempt in range(retries):
        key = ring.current()
        if key is None:
            return None
        url = f"{BASE}?tm={stamp}&cmp=HSR&qcd=HSR&obs=ECHO&map=HB&disp=B&authKey={key}"
        pacer.wait()
        began = time.time()
        if loud:
            print(f"    [추적] {stamp} 시도 {attempt+1}", flush=True)
        try:
            # urlopen's timeout bounds a single socket operation, not the
            # transfer. Once this IP has spent its burst allowance the host
            # keeps the connection open and dribbles bytes, so every read
            # returns in time and the download never ends -- a frame that
            # normally takes seven seconds sat for twenty minutes. A whole
            # frame is 13 MB and arrives in under ten seconds when the host is
            # willing, so give the transfer its own deadline and give up on a
            # throttled one rather than holding the worker.
            with urllib.request.urlopen(url, timeout=20) as handle:
                deadline = time.monotonic() + 45
                chunks, total = [], 0
                while True:
                    piece = handle.read(1 << 18)
                    if not piece:
                        break
                    chunks.append(piece)
                    total += len(piece)
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"throttled at {total/1e6:.1f}MB")
                raw = b"".join(chunks)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 429):
                if ring.retire(key) is None:
                    return None
                continue
            time.sleep(5 * (attempt + 1))
            continue
        except Exception as exc:
            # Connection refused or timed out: the host, not the key. Back off
            # and let the caller's pacing decide whether to keep going.
            if loud:
                print(f"    [추적] {stamp} 실패 {type(exc).__name__}: {exc} "
                      f"({time.time()-began:.1f}s)", flush=True)
            ring.note_connection_failure()
            time.sleep(10 * (attempt + 1))
            continue
        if len(raw) < need:
            if b"result" in raw[:200] or len(raw) < 1000:
                if ring.retire(key) is None:
                    return None
                continue
            time.sleep(2 + attempt)
            continue
        ring.note_success()
        return np.frombuffer(raw[len(raw) - need :], dtype="<i2").astype("float32") / 100.0
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True, help="사건일 목록 JSON")
    parser.add_argument("--points", type=Path, required=True, help="관심 지점 CSV(lon,lat)")
    parser.add_argument("--flood-hours", type=Path,
                        help="사건 -> 침수 시각(시). 주면 그 시각에서 창을 끊는다")
    parser.add_argument("--hours-before", type=int, default=24)
    parser.add_argument("--step-min", type=int, default=10)
    parser.add_argument("--fine-hours", type=int, default=6,
                        help="사건 종료 직전 몇 시간을 --step-min 그대로 받을지.")
    parser.add_argument("--coarse-step-min", type=int, default=60,
                        help="그 이전 구간의 간격. 1~6시간 누적은 정밀 구간에서 "
                             "나오므로 손실이 없고, 24시간 누적만 ±9 mm 흐려진다. "
                             "프레임이 288에서 78로 줄어 같은 할당량으로 사건을 "
                             "네 배 가까이 더 받는다.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-interval", type=float, default=4.0,
                        help="요청 시작 사이 최소 간격(초). 여러 워커의 연결 "
                             "시작이 한꺼번에 몰리지 않게 한다.")
    parser.add_argument("--workers", type=int, default=3,
                        help="동시 다운로드 수. 전송이 병목이라 겹칠 값어치가 "
                             "있지만, 8병렬로 13 MB를 계속 당기자 호스트가 이 IP의 "
                             "연결을 끊었다. 3 정도가 속도와 안전의 타협점이다.")
    parser.add_argument("--retries", type=int, default=4,
                        help="프레임 하나의 네트워크 재시도 횟수")
    parser.add_argument("--block-after", type=int, default=4,
                        help="연속 연결 실패가 이 횟수에 이르면 새 요청을 중단")
    args = parser.parse_args()

    raw_keys = os.environ.get("KMA_APIHUB_KEYS") or os.environ.get("KMA_APIHUB_AUTH_KEY", "")
    ring = KeyRing([k.strip() for k in raw_keys.split(",")])
    if not ring.keys:
        raise SystemExit("KMA_APIHUB_KEYS 또는 KMA_APIHUB_AUTH_KEY 가 없다")
    pacer = Pacer(args.min_interval)
    print(f"[키] {len(ring.keys)}개 준비  |  최소 간격 {args.min_interval}s "
          f"(약 {13.3/args.min_interval:.1f} MB/s)", flush=True)

    lon = np.frombuffer((RADAR / "hsr_lon.bin").read_bytes()[-CELLS * 4 :], dtype="<f4")
    lat = np.frombuffer((RADAR / "hsr_lat.bin").read_bytes()[-CELLS * 4 :], dtype="<f4")

    flood_hour = {}
    if args.flood_hours:
        flood_hour = {k: v for k, v in
                      json.loads(args.flood_hours.read_text(encoding="utf-8")).items()
                      if v is not None}

    pts = []
    point_rows = []
    with args.points.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            pts.append((float(row["lon"]), float(row["lat"])))
            point_rows.append(row)
    pts_arr = np.array(pts)
    print(f"[지점] {len(pts):,}곳", flush=True)

    # Degrees are scaled to rough kilometres so one tree serves the whole
    # country without a projection step; at this latitude the error is well
    # under the 500 m cell.
    tree = cKDTree(np.column_stack([lon * 88.0, lat * 111.0]))
    _, cell_of_point = tree.query(np.column_stack([pts_arr[:, 0] * 88.0, pts_arr[:, 1] * 111.0]))
    print("[매핑] 지점 -> 격자 완료", flush=True)

    events = json.loads(args.events.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)

    for event in events:
        target = args.out / f"rain_{event}.npz"
        if target.exists():
            print(f"[건너뜀] {event} 이미 있음", flush=True)
            continue
        # Without a known flood hour the window has to cover the whole event
        # day and the day before it, because the water could have arrived at
        # any point. Knowing the hour turns 48 hours of frames into 24 and
        # drops the ones that fell after the flood, which were never evidence.
        if event in flood_hour:
            end = (datetime.strptime(event, "%Y%m%d")
                   + timedelta(hours=int(flood_hour[event])))
            start = end - timedelta(hours=args.hours_before)
        else:
            end = datetime.strptime(event, "%Y%m%d") + timedelta(days=1)
            start = end - timedelta(hours=args.hours_before + 24)
        fine_start = end - timedelta(hours=args.fine_hours)
        stamps, spans = [], []
        cursor = start
        while cursor < end:
            step = args.step_min if cursor >= fine_start else args.coarse_step_min
            stamps.append(cursor.strftime("%Y%m%d%H%M"))
            spans.append(step)
            cursor += timedelta(minutes=step)

        series = np.full((len(stamps), len(pts)), np.nan, dtype="float32")
        started, done, ok = time.time(), 0, 0
        last_report = started

        def grab(pair):
            index, stamp = pair
            return index, fetch(stamp, ring, pacer, retries=args.retries)

        # Executor.map eagerly queues the entire event. If the IP becomes
        # blocked, breaking its result loop still leaves every queued request
        # alive and shutdown waits for them all. Keep only `workers` requests
        # in flight so a stop condition can cancel the small pending set.
        pool = ThreadPoolExecutor(max_workers=args.workers)
        pending = set()
        next_index = 0
        stopped = False
        try:
            while next_index < min(args.workers, len(stamps)):
                pending.add(pool.submit(grab, (next_index, stamps[next_index])))
                next_index += 1
            while pending:
                finished, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in finished:
                    index, dbz = future.result()
                    done += 1
                    if dbz is not None:
                        series[index] = rain_rate(dbz)[cell_of_point]
                        ok += 1
                    if ring.current() is None:
                        print(f"[중단] 모든 키 소진. {event} {done}/{len(stamps)}까지",
                              flush=True)
                        stopped = True
                        break
                    if ring.blocked(args.block_after):
                        print(f"[중단] 연결이 계속 거부된다 — 키가 아니라 접속 차단으로 "
                              f"보인다. {event} {done}/{len(stamps)}까지", flush=True)
                        stopped = True
                        break
                    # Report on a clock, not a frame count: at one worker a
                    # 24-frame interval is half an hour of silence, which is
                    # indistinguishable from a hung run.
                    if time.time() - last_report >= 30:
                        last_report = time.time()
                        elapsed = max(time.time() - started, 1)
                        rate = done / elapsed
                        left = (len(stamps) - done) / max(rate, 1e-6)
                        mbps = ok * 13.3 / elapsed
                        print(f"  {event} {done}/{len(stamps)}  성공 {ok}  "
                              f"{rate*60:.0f}프레임/분  {mbps:.1f} MB/s  "
                              f"남은 {left/60:.0f}분", flush=True)
                if stopped:
                    break
                while next_index < len(stamps) and len(pending) < args.workers:
                    pending.add(pool.submit(grab, (next_index, stamps[next_index])))
                    next_index += 1
        finally:
            for future in pending:
                future.cancel()
            pool.shutdown(wait=True, cancel_futures=True)
        # A run cut short by an exhausted key must not leave a file behind:
        # the next run skips anything already written, so a stub would quietly
        # retire an event that was never collected.
        if ok < len(stamps) * 0.9:
            print(f"[미저장] {event}  {ok}/{len(stamps)}프레임만 받아 저장하지 않음 "
                  f"(다음 실행에서 다시 시도)", flush=True)
            if ring.current() is None:
                break
            continue
        # Frames no longer sit on one cadence, so each one's span is stored
        # alongside it: an accumulation is a span-weighted sum, and without the
        # spans a coarse frame would be read as if it covered ten minutes.
        # The point list is stored with the series. A file that only carries a
        # column count silently mismatches a point file drawn later, and the
        # mismatch surfaces as an index error deep in a downstream join rather
        # than where the two disagree.
        np.savez_compressed(target, series=series, stamps=np.array(stamps),
                            span_min=np.array(spans, dtype="int16"),
                            step_min=args.step_min,
                            lon=pts_arr[:, 0], lat=pts_arr[:, 1],
                            kind=np.array([p["kind"] for p in point_rows]),
                            owner=np.array([p["event"] for p in point_rows]))
        print(f"[저장] {event}  {ok}/{len(stamps)}프레임  {time.time()-started:.0f}s  "
              f"{target.stat().st_size/1e6:.1f}MB", flush=True)


if __name__ == "__main__":
    main()
