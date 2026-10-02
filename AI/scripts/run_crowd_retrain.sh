#!/usr/bin/env bash
# CROWD 재학습 러너(app.CROWD.pipeline.retrain.run)를 한 번 돌린다(systemd 타이머가 호출).
# 첫 달은 타이머를 enable 하지 않고 수동 실행한다: bash scripts/run_crowd_retrain.sh --force
# 로그 파일은 systemd StandardOutput=append:가 받으므로 여기서 직접 열지 않는다.
# 관측 지표: 환경변수 SUMGIL_TEXTFILE_DIR가 있으면 종료 시 node-exporter textfile(.prom)을 쓴다(없으면 건너뜀, 배치 결과에 영향 없음).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python
fi
export PYTHONIOENCODING=utf-8 TZ=Asia/Seoul

# 종료 시(성공·실패 모두) 관측 지표 textfile을 쓴다. 실패해도 배치 종료 코드는 바꾸지 않는다.
T0=$(date +%s)
STEP_RCS=()
export_metrics() {
  local rc=$?
  local STEP_ARGS=() s
  for s in ${STEP_RCS[@]+"${STEP_RCS[@]}"}; do STEP_ARGS+=(--step "$s"); done
  "$PY" -m DATA_ENGINE.observability.export_textfile --job crowd_retrain --rc "$rc" \
    --duration "$(( $(date +%s) - T0 ))" ${STEP_ARGS[@]+"${STEP_ARGS[@]}"} \
    --ok-rc 0 --ok-rc 99 || true
}
trap export_metrics EXIT

start=$(date +%s)
rc=0
"$PY" -m app.CROWD.pipeline.retrain.run --python "$PY" "$@" || rc=$?
STEP_RCS+=("run=${rc}")
echo "[crowd_retrain] rc=${rc} sec=$(($(date +%s) - start))"

# rc 99는 재학습 요청 없음·야간창 밖·수집 재처리 중 같은 정상 skip이다.
if [ "$rc" -eq 99 ]; then
  echo "[crowd_retrain] skip - 재학습 조건 아님(정상 종료로 처리)"
  exit 0
fi
exit "$rc"
