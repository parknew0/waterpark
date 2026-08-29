#!/usr/bin/env python3
"""Rainfall at flood sites and controls, read from the 500 m radar composite.

The service currently reads rain from ~660 gauges, whose nearest neighbours sit
8 km apart. On 2022-08-08 the 90th percentile of the difference between one
gauge and its closest neighbour was 26.7 mm/h — wider than the 30 mm that
separates a 호우주의보 from a 호우경보. Interpolating between gauges therefore
decides the alert level by accident as often as by measurement.

The radar composite is 2305 x 2881 at 500 m. With ``--grid-out`` the original
int16 national grid is archived as well as the much smaller point series. This
lets later analyses choose new controls or neighbourhoods without spending the
API allowance a second time.

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
import socket
import subprocess
import sys
import threading
import tempfile
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
RADAR = ROOT / "data/interim/radar"
NX, NY = 2305, 2881
CELLS = NX * NY
# The large-volume service lives on its own hostname with its own allowance
# (2 TB a day against 5 GB), so the host is configurable rather than fixed.
API_HOST = os.environ.get("KMA_APIHUB_HOST", "apihub.kma.go.kr")
BASE = f"https://{API_HOST}/api/typ01/cgi-bin/url/nph-rdr_cmp1_api"

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


def fetch(stamp: str, ring: "KeyRing", pacer: "Pacer", api_ip: str,
          retries: int = 4) -> np.ndarray | None:
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
            # urllib's timeout is not a whole-request deadline: address
            # resolution/connection attempts can run before it, and a server
            # that dribbles bytes can keep resetting the socket timeout. curl's
            # --max-time covers DNS, connection and transfer together. Feed the
            # URL through stdin so the API key is not exposed in the process
            # command line.
            escaped_url = url.replace("\\", "\\\\").replace('"', '\\"')
            config = f'url = "{escaped_url}"\n'.encode()
            response = subprocess.run(
                [
                    "/usr/bin/curl",
                    "--silent",
                    "--show-error",
                    # The host accepts connections slowly once this IP has
                    # pulled a lot in a day -- a hand-run curl still succeeds
                    # while a 10 s limit fails two frames in three. Waiting
                    # longer for the handshake costs nothing when it is going
                    # to arrive, and the transfer deadline still bounds a
                    # throttled download.
                    "--connect-timeout", "40",
                    "--max-time", "120",
                    "--resolve", f"{API_HOST}:443:{api_ip}",
                    "--output", "-",
                    "--config", "-",
                ],
                input=config,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=130,
                check=False,
            )
            if response.returncode:
                message = response.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"curl {response.returncode}: {message}")
            raw = response.stdout
        except Exception as exc:
            # Connection refused or timed out: the host, not the key. Back off
            # and let the caller's pacing decide whether to keep going.
            elapsed = time.time() - began
            if loud:
                print(f"    [추적] {stamp} 실패 {type(exc).__name__}: {exc} "
                      f"({elapsed:.1f}s)", flush=True)
            # An IP block has presented as an immediate (HTTP 000) connection
            # refusal. A 20-second read timeout on one historical timestamp is
            # instead a slow/missing archive frame and must not trip the global
            # block circuit for all later timestamps.
            if elapsed < 2.0:
                ring.note_connection_failure()
            time.sleep(10 * (attempt + 1))
            continue
        if len(raw) < need:
            # "# CMP 합성 자료가 없음" is the archive saying this timestamp was
            # never recorded -- common near 2014, where the radar composite
            # begins. It is not a spent key, and retiring one for it killed a
            # run whose key still had 2 TB left. Only the JSON quota error
            # retires a key.
            if raw[:1] == b"#" or b"CMP" in raw[:40]:
                return None                      # 그 시각 자료가 애초에 없다
            # Retire a key only on the hub's own quota answer. Anything else
            # short -- an empty body, a cut-off transfer -- is the network
            # having a bad moment, and treating it as a spent key threw away a
            # key with 2 TB left and stopped the run three times.
            quota = b"result" in raw[:200] and (b"403" in raw[:400]
                                                or "용량".encode() in raw[:400])
            if quota:
                if ring.retire(key) is None:
                    return None
                continue
            time.sleep(2 + attempt)
            continue
            time.sleep(2 + attempt)
            continue
        ring.note_success()
        # Keep the provider's compact int16 representation. Converting the
        # whole country to float32 here doubles memory and, more importantly,
        # makes it impossible to preserve the exact response for reuse.
        return np.frombuffer(raw[len(raw) - need :], dtype="<i2").copy()
    return None


def save_npz_atomic(target: Path, **arrays: object) -> None:
    """Write a compressed archive without exposing a partial final file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f"{target.name}.part")
    try:
        with partial.open("wb") as handle:
            np.savez_compressed(handle, **arrays)
            handle.flush()
            os.fsync(handle.fileno())
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


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
    parser.add_argument("--grid-out", type=Path,
                        help="원본 전국 격자 NPZ 저장 폴더. 생략하면 지점 시계열만 저장")
    parser.add_argument("--grid-temp", type=Path,
                        help="격자 압축 전 임시 파일 폴더(기본: 시스템 임시 폴더)")
    parser.add_argument("--min-interval", type=float, default=0.5,
                        help="요청 시작 사이 최소 간격(초). 여러 워커의 연결 "
                             "시작이 한꺼번에 몰리지 않게 한다.")
    parser.add_argument("--workers", type=int, default=1,
                        help="동시 다운로드 수. 8병렬 수집 뒤 IP가 차단된 전력이 "
                             "있어 기본값은 1이다.")
    parser.add_argument("--retries", type=int, default=4,
                        help="프레임 하나의 네트워크 재시도 횟수")
    parser.add_argument("--repair-rounds", type=int, default=2,
                        help="사건의 나머지 프레임을 저장 전에 다시 훑는 횟수")
    parser.add_argument("--block-after", type=int, default=4,
                        help="연속 연결 실패가 이 횟수에 이르면 새 요청을 중단")
    args = parser.parse_args()

    raw_keys = os.environ.get("KMA_APIHUB_KEYS") or os.environ.get("KMA_APIHUB_AUTH_KEY", "")
    ring = KeyRing([k.strip() for k in raw_keys.split(",")])
    if not ring.keys:
        raise SystemExit("KMA_APIHUB_KEYS 또는 KMA_APIHUB_AUTH_KEY 가 없다")
    pacer = Pacer(args.min_interval)
    try:
        # Resolve once per run. Repeating synchronous DNS lookup for every
        # frame let one lookup sit outside curl's 45-second transfer deadline
        # for more than six minutes. --resolve below keeps TLS/SNI validation
        # on the hostname while connecting to this resolved address directly.
        api_ip = socket.gethostbyname(API_HOST)
    except OSError as exc:
        raise SystemExit(f"{API_HOST} 주소 확인 실패: {exc}") from exc
    print(f"[키] {len(ring.keys)}개 준비  |  최소 간격 {args.min_interval}s "
          f"(약 {13.3/args.min_interval:.1f} MB/s)", flush=True)
    print(f"[호스트] {API_HOST} -> {api_ip} (실행 중 DNS 재조회 안 함)", flush=True)

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
    if args.grid_out:
        args.grid_out.mkdir(parents=True, exist_ok=True)
    if args.grid_temp:
        args.grid_temp.mkdir(parents=True, exist_ok=True)

    for event in events:
        point_target = args.out / f"rain_{event}.npz"
        grid_target = (args.grid_out / f"rain_{event}_grid.npz"
                       if args.grid_out else None)
        need_point = not point_target.exists()
        need_grid = grid_target is not None and not grid_target.exists()
        if not need_point and not need_grid:
            print(f"[건너뜀] {event} 지점·격자 이미 있음", flush=True)
            continue
        wanted = []
        if need_point:
            wanted.append("지점")
        if need_grid:
            wanted.append("전국 격자")
        print(f"[시작] {event}  저장 대상: {', '.join(wanted)}", flush=True)
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

        series = (np.full((len(stamps), len(pts)), np.nan, dtype="float32")
                  if need_point else None)
        grid_tmp = None
        grid = None
        if need_grid:
            grid_tmp = tempfile.TemporaryDirectory(
                prefix=f"waterpark-radar-{event}-",
                dir=str(args.grid_temp) if args.grid_temp else None,
            )
            grid = np.memmap(
                Path(grid_tmp.name) / "grid.i2",
                dtype="<i2",
                mode="w+",
                shape=(len(stamps), NY, NX),
            )
        started, done, ok = time.time(), 0, 0
        last_report = started
        received = np.zeros(len(stamps), dtype=bool)

        def keep(index: int, raw_grid: np.ndarray) -> None:
            """Put one response in every requested output exactly once."""
            nonlocal ok
            if received[index]:
                return
            if series is not None:
                point_dbz = raw_grid[cell_of_point].astype("float32") / 100.0
                series[index] = rain_rate(point_dbz)
            if grid is not None:
                grid[index] = raw_grid.reshape(NY, NX)
            received[index] = True
            ok += 1

        def grab(pair):
            index, stamp = pair
            return index, fetch(stamp, ring, pacer, api_ip, retries=args.retries)

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
                    index, raw_grid = future.result()
                    done += 1
                    if raw_grid is not None:
                        keep(index, raw_grid)
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

        # Old archives occasionally stall on an individual timestamp while
        # the frames around it work. Re-request only those holes; throwing
        # away the other 38 national grids would waste both quota and time.
        if not stopped and need_grid and ok < len(stamps):
            for repair_round in range(1, args.repair_rounds + 1):
                missing = np.flatnonzero(~received)
                if not len(missing):
                    break
                print(f"[보충 {repair_round}/{args.repair_rounds}] {event}  "
                      f"빠진 프레임 {len(missing)}개", flush=True)
                for index in missing:
                    raw_grid = fetch(stamps[index], ring, pacer, api_ip,
                                     retries=args.retries)
                    if raw_grid is not None:
                        keep(int(index), raw_grid)
                    if ring.current() is None or ring.blocked(args.block_after):
                        stopped = True
                        break
                if stopped:
                    break
        # A run cut short by an exhausted key must not leave a file behind:
        # the next run skips anything already written, so a stub would quietly
        # retire an event that was never collected.
        if need_point and ok >= len(stamps) * 0.9:
            save_npz_atomic(
                point_target,
                series=series,
                stamps=np.array(stamps),
                span_min=np.array(spans, dtype="int16"),
                step_min=args.step_min,
                lon=pts_arr[:, 0],
                lat=pts_arr[:, 1],
                kind=np.array([p["kind"] for p in point_rows]),
                owner=np.array([p["event"] for p in point_rows]),
            )
            print(f"[지점 저장] {event}  {ok}/{len(stamps)}프레임  "
                  f"{point_target.stat().st_size/1e6:.1f}MB", flush=True)

        # Keep only frames that actually arrived. Missing int16 rows cannot be
        # represented by floating-point NaN, so saving an uninitialised full
        # array would create plausible-looking false observations. The archive
        # records requested/downloaded counts and the missing timestamps.
        if need_grid and ok >= len(stamps) * 0.9:
            assert grid is not None and grid_target is not None
            grid.flush()
            valid_index = np.flatnonzero(received)
            missing_stamps = np.array(stamps)[~received]
            print(f"[격자 압축] {event}  {ok}/{len(stamps)}프레임", flush=True)
            save_npz_atomic(
                grid_target,
                grid=grid[valid_index],
                stamps=np.array(stamps)[received],
                span_min=np.array(spans, dtype="int16")[received],
                missing_stamps=missing_stamps,
                requested_count=np.int32(len(stamps)),
                downloaded_count=np.int32(ok),
                event=np.array(event),
                nx=np.int32(NX),
                ny=np.int32(NY),
                cell_m=np.int32(500),
                dbz_scale=np.float32(0.01),
                dbz_unit=np.array("dBZ"),
                layout=np.array("grid[frame,y,x], C-order"),
                outside_coverage_raw=np.int16(-30000),
                no_echo_raw=np.int16(-25000),
                lon_file=np.array("data/interim/radar/hsr_lon.bin"),
                lat_file=np.array("data/interim/radar/hsr_lat.bin"),
                source=np.array(BASE),
            )
            print(f"[격자 저장] {event}  {grid_target.stat().st_size/1e6:.1f}MB",
                  flush=True)

        if grid is not None:
            del grid
        if grid_tmp is not None:
            grid_tmp.cleanup()

        if ok < len(stamps) * 0.9:
            print(f"[미저장] {event}  {ok}/{len(stamps)}프레임만 받아 저장하지 않음 "
                  f"(다음 실행에서 다시 시도)", flush=True)
            if ring.current() is None:
                break
            if stopped and ring.blocked(args.block_after):
                print("[전체 중단] 접속 차단 상태에서 다음 사건을 건드리지 않음",
                      flush=True)
                break
            continue
        if need_grid and ok < len(stamps) * 0.9:
            print(f"[격자 미저장] {event}  완전한 {len(stamps)}프레임 중 "
                  f"{ok}개만 받아 다음 실행에서 다시 시도", flush=True)
        print(f"[완료] {event}  {ok}/{len(stamps)}프레임  "
              f"{time.time()-started:.0f}s", flush=True)


if __name__ == "__main__":
    main()
