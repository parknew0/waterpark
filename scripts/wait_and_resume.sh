#!/bin/sh
# 15:00(사용 가능 시각)이 될 때까지 기다렸다가 자동으로 재개한다.
cd "$(dirname "$0")/.." || exit 1
while true; do
  now=$(date +%H%M)
  if [ "$now" -ge 1500 ] && [ "$now" -lt 2400 ]; then
    echo "$(date '+%H:%M:%S') 사용 시간 진입 -> 재개"
    ./scripts/resume_radar.sh
    break
  fi
  sleep 60
done
