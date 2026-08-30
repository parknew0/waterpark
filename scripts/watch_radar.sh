#!/bin/sh
# 레이더 수집을 실시간으로 지켜본다.
#   ./scripts/watch_radar.sh          2초마다 새로 그림 (Ctrl-C 로 나감)
#   ./scripts/watch_radar.sh 5        5초마다
cd "$(dirname "$0")/.." || exit 1
LOG=${RADAR_LOG:-/tmp/news_radar.log}
EVENTS=${RADAR_EVENTS:-config/radar/events_from_news.json}
GAP=${1:-2}
exec ./.venv/bin/python scripts/watch_radar.py --log "$LOG" --events "$EVENTS" --gap "$GAP"
