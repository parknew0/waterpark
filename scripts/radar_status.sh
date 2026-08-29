#!/bin/sh
# 지금 수집이 돌고 있는지, 어디까지 갔는지 한 눈에.
cd "$(dirname "$0")/.." || exit 1
if pgrep -f 'collect_radar_rainfall.py --events' > /dev/null; then
  echo "상태: 실행 중 (PID $(pgrep -f 'collect_radar_rainfall.py --events' | tail -1))"
else
  echo "상태: 멈춤  ->  ./scripts/resume_radar.sh 로 재개"
fi
done_n=$(ls data/interim/radar/events_full/*.npz 2>/dev/null | wc -l | tr -d ' ')
total=$(grep -o '"' config/radar/events_all.json | wc -l | tr -d ' ')
echo "완료: ${done_n} / $((total / 2)) 사건    저장: $(du -sh data/interim/radar/grids_full 2>/dev/null | cut -f1)"
echo "현재:"
grep '프레임/분' /tmp/full.log 2>/dev/null | tail -1 | sed 's/^/  /'
grep '저장' /tmp/full.log 2>/dev/null | tail -3 | sed 's/^/  /'
