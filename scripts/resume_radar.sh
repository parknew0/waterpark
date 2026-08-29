#!/bin/sh
# Resume the full radar collection. Safe to run repeatedly: events already
# saved are skipped, and a partial event is discarded rather than left looking
# finished. The large-volume service is only open 15:00-24:00 KST, so outside
# those hours this will simply fail every frame and save nothing.
cd "$(dirname "$0")/.." || exit 1
set -a; . ./.env; set +a
KMA_APIHUB_HOST="$KMA_APIHUB_ORG_HOST" \
KMA_APIHUB_KEYS="$KMA_APIHUB_ORG_KEY" \
nohup ./.venv/bin/python scripts/collect_radar_rainfall.py \
  --events config/radar/events_all.json \
  --points config/radar/radar_points3.csv \
  --flood-hours config/radar/flood_hours_plus6.json \
  --hours-before 48 --step-min 10 --fine-hours 48 \
  --workers 16 --min-interval 0.2 --block-after 30 \
  --out data/interim/radar/events_full \
  --grid-out data/interim/radar/grids_full >> /tmp/full.log 2>&1 &
echo "재개: PID $!  (진행 상황: tail -f /tmp/full.log)"
