#!/bin/sh
# 밤새 돌린다. 앞 단계 결과를 뒤 단계가 받아 쓰므로 순서대로 이어 붙인다.
#
#   1) 설정 훑기      하나씩 15 + 무작위 30 -> 여섯 묶음 중 다섯으로 확인
#   2) 알고리즘 비교   XGBoost / LightGBM / CatBoost / 셋 섞기
#   3) 좁혀서 다시 훑기 1)이 고른 설정 둘레를 무작위 40 가지로
#   4) 마지막 앙상블   3)이 고른 설정으로 세 알고리즘을 다시 섞는다
#
# 각 단계는 앞 단계가 끝나야 시작한다. 하나가 실패해도 다음은 돈다.
cd "$(dirname "$0")/.." || exit 1
PY=./.venv/bin/python
log() { printf '\n===== %s  %s =====\n' "$1" "$(date '+%m-%d %H:%M')" >> /tmp/overnight.log; }

log "1) 설정 훑기"
$PY scripts/eval_hyper_sweep.py > /tmp/sweep.log 2>&1

log "2) 알고리즘 비교"
$PY scripts/eval_libraries.py > /tmp/libs.log 2>&1

log "3) 좁혀서 다시 훑기"
$PY scripts/eval_hyper_refine.py > /tmp/refine.log 2>&1

log "4) 마지막 앙상블"
$PY scripts/eval_final_ensemble.py > /tmp/final.log 2>&1

log "전부 끝"
