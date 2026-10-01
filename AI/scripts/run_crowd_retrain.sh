#!/usr/bin/env bash
# CROWD 재학습 러너(app.CROWD.pipeline.retrain.run)를 한 번 돌린다(systemd 타이머가 호출).
# 첫 달은 타이머를 enable 하지 않고 수동 실행한다: bash scripts/run_crowd_retrain.sh --force
# 로그 파일은 systemd StandardOutput=append:가 받으므로 여기서 직접 열지 않는다.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python
fi
export PYTHONIOENCODING=utf-8 TZ=Asia/Seoul

start=$(date +%s)
rc=0
"$PY" -m app.CROWD.pipeline.retrain.run --python "$PY" "$@" || rc=$?
echo "[crowd_retrain] rc=${rc} sec=$(($(date +%s) - start))"

# rc 99는 재학습 요청 없음·야간창 밖·수집 재처리 중 같은 정상 skip이다.
if [ "$rc" -eq 99 ]; then
  echo "[crowd_retrain] skip - 재학습 조건 아님(정상 종료로 처리)"
  exit 0
fi
exit "$rc"
