#!/bin/sh
# 2023년 침수일 중 레이더가 없는 7일을 받는다.
# 대용량 서비스는 15~24시에만 열리므로 그때까지 기다렸다 시작한다.
cd "$(dirname "$0")/.." || exit 1
while [ "$(date +%H)" -lt 15 ]; do sleep 300; done
set -a; . ./.env; set +a
KMA_APIHUB_HOST="$KMA_APIHUB_ORG_HOST" KMA_APIHUB_KEYS="$KMA_APIHUB_ORG_KEY" \
exec ./.venv/bin/python scripts/collect_radar_rainfall.py \
  --events config/radar/events_2023_missing.json \
  --points config/radar/radar_points3.csv \
  --flood-hours config/radar/flood_hours_plus.json \
  --hours-before 48 --step-min 10 --fine-hours 48 \
  --workers 16 --min-interval 0.2 --block-after 30 \
  --out data/interim/radar/events_full \
  --grid-out data/interim/radar/grids_full
