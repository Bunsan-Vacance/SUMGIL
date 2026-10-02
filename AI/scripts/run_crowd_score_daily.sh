#!/usr/bin/env bash
# 예측 판 아카이브 → 일별 채점 → 드리프트 판정 → 리포트를 한 번에 돌린다(systemd 타이머가 호출).
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
  "$PY" -m DATA_ENGINE.observability.export_textfile --job crowd_score_daily --rc "$rc" \
    --duration "$(( $(date +%s) - T0 ))" ${STEP_ARGS[@]+"${STEP_ARGS[@]}"} \
    --ok-rc 0 --ok-rc 99 || true
}
trap export_metrics EXIT

# run_step <이름> <명령...> — 명령의 종료 코드를 돌려주고 한 줄 요약을 남긴다.
run_step() {
  local name="$1"
  shift
  local start rc=0
  start=$(date +%s)
  "$@" || rc=$?
  STEP_RCS+=("${name}=${rc}")
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

# shadow 후보(shadow_candidates.json)가 있으면 후보별 예측 판도 같은 규칙으로 채점한다.
# 입력은 data/CROWD/shadow/<후보명>/, 출력은 monitoring/score_shadow/<후보명>/ — 챔피언 채점(score_daily)과
# 섞이지 않게 분리하고, `gate shadow --champion-score-dir … --shadow-score-dir …`가 둘을 나란히 읽는다.
CANDIDATES="data/CROWD/monitoring/shadow_candidates.json"
if [ -f "$CANDIDATES" ]; then
  for name in $("$PY" -c 'import json,sys; [print(c["artifact"] if isinstance(c, dict) else c) for c in json.load(open(sys.argv[1], encoding="utf-8")).get("candidates", [])]' "$CANDIDATES"); do
    if [ ! -d "data/CROWD/shadow/$name" ]; then
      echo "[score_daily] shadow 후보 $name: 예측 판 없음(data/CROWD/shadow/$name) - 건너뜀"
      continue
    fi
    rc=0
    run_step "score_shadow:$name" "$PY" -m app.CROWD.pipeline.retrain.score --catch-up-days 7       --serving-dir "data/CROWD/shadow/$name"       --archive-dir "data/CROWD/monitoring/pred_archive_shadow/$name"       --out-dir "data/CROWD/monitoring/score_shadow/$name" || rc=$?
    if [ "$rc" -ne 0 ] && [ "$rc" -ne 99 ]; then
      exit "$rc"
    fi
  done
fi

run_step drift "$PY" -m app.CROWD.pipeline.retrain.drift
run_step report "$PY" -m app.CROWD.pipeline.retrain.report
