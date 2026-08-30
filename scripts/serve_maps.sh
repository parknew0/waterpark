#!/bin/sh
# 침수 지도 뷰어를 로컬에 띄운다.
#   ./scripts/serve_maps.sh            전국 30 m 타일 (8767)
#   ./scripts/serve_maps.sh coarse     전국 한 장 그림, 240 m (8766)
#   ./scripts/serve_maps.sh seoul      서울·강남 상세 (8765)
#   ./scripts/serve_maps.sh stop       둘 다 끈다
cd "$(dirname "$0")/.." || exit 1
PY=./.venv/bin/python

case "${1:-national}" in
  stop)
    pkill -f "http.server 8765" 2>/dev/null
    pkill -f "http.server 8766" 2>/dev/null
    pkill -f "http.server 8767" 2>/dev/null
    echo "지도 서버를 껐습니다."
    exit 0 ;;
  seoul)  DIR=outputs/flood-map-demo;     PORT=8765; NAME="서울·강남 상세 (30 m)" ;;
  coarse) DIR=outputs/flood-map-national; PORT=8766; NAME="전국 한 장 그림 (240 m)" ;;
  *)      DIR=outputs/flood-map-tiles;    PORT=8767; NAME="전국 30 m (타일)" ;;
esac

if [ ! -f "$DIR/index.html" ]; then
  echo "지도가 아직 없습니다. 먼저 만드세요:"
  case "$PORT" in
    8767) echo "  $PY scripts/build_flood_tiles.py            (약 1시간 반)" ;;
    8766) echo "  $PY scripts/build_flood_map_national.py     (약 1시간)" ;;
    *)    echo "  $PY scripts/build_flood_map_demo.py         (약 3분)" ;;
  esac
  exit 1
fi

pkill -f "http.server $PORT" 2>/dev/null
sleep 1
nohup $PY -m http.server "$PORT" -d "$DIR" >/dev/null 2>&1 &
sleep 1
echo "$NAME"
echo "  http://localhost:$PORT   (끄기: ./scripts/serve_maps.sh stop)"
