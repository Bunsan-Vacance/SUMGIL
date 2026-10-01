#!/usr/bin/env bash
# shadow_candidates.json에 등록된 후보마다 배치 예측을 돌려 data/CROWD/shadow/<후보명>/에 쌓는다.
# 챔피언의 serving/·score_daily/는 건드리지 않는다. 로그는 systemd StandardOutput=append:가 받는다.
#
# 후보 아티팩트 지정: 배치는 settings.crowd_lgbm_artifact(env CROWD_LGBM_ARTIFACT)를
# `crowd_models_dir / <값>`으로 읽는다. 값이 절대경로면 그 경로가 그대로 쓰이므로(Path 결합 규칙)
# env에 후보 폴더 절대경로를 넣는다.
set -uo pipefail
cd "$(dirname "$0")/.."

if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python
fi
export PYTHONIOENCODING=utf-8 TZ=Asia/Seoul
AI_ROOT="$(pwd)"
LIST="data/CROWD/monitoring/shadow_candidates.json"

if [ ! -f "$LIST" ]; then
  echo "[shadow_predict] 후보 등록 파일 없음($LIST) - 할 일 없음"
  exit 0
fi

# 후보 이름을 한 줄씩 뽑는다.
names=$("$PY" - "$LIST" <<'PYEOF'
import json
import sys

for item in json.load(open(sys.argv[1], encoding="utf-8")).get("candidates", []):
    if item.get("artifact"):
        print(item["artifact"])
PYEOF
)

if [ -z "$names" ]; then
  echo "[shadow_predict] 등록된 후보 없음 - 할 일 없음"
  exit 0
fi

fail=0
while IFS= read -r name; do
  [ -z "$name" ] && continue
  art="$AI_ROOT/models/CROWD/_experiments/auto/$name"
  [ -d "$art" ] || art="$AI_ROOT/models/CROWD/$name"
  if [ ! -d "$art" ]; then
    echo "[shadow_predict] 후보=${name} 아티팩트 폴더 없음 - 건너뜀"
    fail=1
    continue
  fi
  start=$(date +%s)
  rc=0
  CROWD_LGBM_ARTIFACT="$art" bash DATA_ENGINE/scripts/run_crowd_batch_predict.sh \
    --out-dir "data/CROWD/shadow/${name}/" || rc=$?
  echo "[shadow_predict] 후보=${name} rc=${rc} sec=$(($(date +%s) - start))"
  [ "$rc" -eq 0 ] || fail=1
done <<< "$names"

exit "$fail"
