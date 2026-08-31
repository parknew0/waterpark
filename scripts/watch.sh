#!/bin/sh
# 돌고 있는 채점·검증·수집을 한 화면에서 본다.
#   ./scripts/watch.sh        3초마다
#   ./scripts/watch.sh 10     10초마다
cd "$(dirname "$0")/.." || exit 1
exec ./.venv/bin/python scripts/watch_eval.py --gap "${1:-3}"
