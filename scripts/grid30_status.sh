#!/bin/sh
# 30 m 격자 재구축 진행 상황. 다른 터미널에서 반복 실행하거나
#   watch -n 10 ./scripts/grid30_status.sh
cd "$(dirname "$0")/.." || exit 1
S=data/interim/grid30/status.json
[ -f data/interim/grid30/census_status.json ] && S=data/interim/grid30/census_status.json
if pgrep -f 'build_grid30.py|build_ring_census30.py' > /dev/null; then
  echo "상태: 실행 중 (PID $(pgrep -f 'build_grid30.py|build_ring_census30.py' | head -1))"
else
  echo "상태: 멈춤"
fi
[ -f "$S" ] || { echo "아직 시작 전"; exit 0; }
./.venv/bin/python - "$S" <<'PY'
import json,sys
d=json.load(open(sys.argv[1],encoding="utf-8"))
print(f"단계: {d.get('step','?')}  {d.get('percent','?')}%   (갱신 {d.get('updated','?')})")
print(f"  {d.get('message','')}")
print("\n최근 기록:")
for line in d.get("history",[])[-8:]:
    print("  "+line)
PY
echo
echo "생성된 파일:"
ls -la data/interim/grid30/*.npy 2>/dev/null | awk '{printf "  %-40s %6.2f GB\n",$NF,$5/1073741824}' || echo "  아직 없음"
