#!/usr/bin/env bash
# 예측 판 아카이브 → 일별 채점 → 드리프트 판정 → 리포트를 한 번에 돌린다(systemd 타이머가 호출).
# 로그 파일은 systemd StandardOutput=append:가 받으므로 여기서 직접 열지 않는다.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python
fi
export PYTHONIOENCODING=utf-8 TZ=Asia/Seoul

# run_step <이름> <명령...> — 명령의 종료 코드를 돌려주고 한 줄 요약을 남긴다.
run_step() {
  local name="$1"
  shift
  local start rc=0
  start=$(date +%s)
  "$@" || rc=$?
  echo "[score_daily] step=${name} rc=${rc} sec=$(($(date +%s) - start))"
  return "$rc"
}

run_step archive "$PY" -m app.CROWD.pipeline.retrain.archive

# score는 새로 채점된 날 없이 보류만 있으면 99를 낸다 — 실측이 아직 안 온 정상 상황이다.
rc=0
run_step score "$PY" -m app.CROWD.pipeline.retrain.score --catch-up-days 7 || rc=$?
if [ "$rc" -eq 99 ]; then
  echo "[score_daily] score rc=99 - 새로 채점된 날 없음(실측 대기), 정상 종료로 처리"
elif [ "$rc" -ne 0 ]; then
  exit "$rc"
fi

run_step drift "$PY" -m app.CROWD.pipeline.retrain.drift
run_step report "$PY" -m app.CROWD.pipeline.retrain.report
