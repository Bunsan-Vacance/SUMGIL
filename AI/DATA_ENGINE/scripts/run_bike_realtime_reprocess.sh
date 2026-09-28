#!/usr/bin/env bash
# 274 — 따릉이 재고 raw 누적 재집계·품질 리포트 (상시 배치, 결정문서 1순위 후보).
#
# 서빙에 안 쓰인다 — data/BIKE/processed/realtime_stock_profile/에 품질 리포트로만 쓴다.
set -uo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
if [[ "${SCRIPT_SOURCE}" == */* ]]; then
  SCRIPT_DIR="$(cd "${SCRIPT_SOURCE%/*}" && pwd)"
else
  SCRIPT_DIR="$(pwd)"
fi
AI_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ -x "${AI_ROOT}/.venv/bin/python" ]]; then
  PYTHON="${AI_ROOT}/.venv/bin/python"
elif [[ -x "${AI_ROOT}/.venv/Scripts/python.exe" ]]; then
  PYTHON="${AI_ROOT}/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  printf '%s\n' "FAIL python executable not found"
  exit 1
fi

# Spark(JVM) 실행에 Java가 필요하다. JAVA_HOME이 이미 설정돼 있으면 그대로 쓰고,
# 아니면 Debian/Ubuntu apt 설치 표준 심볼릭 링크를 시도한다(update-alternatives가 관리).
if [[ -z "${JAVA_HOME:-}" ]]; then
  if [[ -d /usr/lib/jvm/default-java ]]; then
    export JAVA_HOME=/usr/lib/jvm/default-java
  elif command -v java >/dev/null 2>&1; then
    export JAVA_HOME="$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")"
  fi
fi
if [[ -z "${JAVA_HOME:-}" ]] || [[ ! -x "${JAVA_HOME}/bin/java" ]]; then
  printf '%s\n' "FAIL Java not found — sudo apt install -y default-jdk-headless 먼저 필요"
  exit 1
fi

cd "${AI_ROOT}"

printf '%s\n' "[bike realtime reprocess] start: $(date -Is)"
printf '%s\n' "[bike realtime reprocess] python: ${PYTHON}"
printf '%s\n' "[bike realtime reprocess] JAVA_HOME: ${JAVA_HOME}"

"${PYTHON}" -m DATA_ENGINE.spark.jobs.bike_realtime_reprocess "$@"
status=$?

if [[ "${status}" -eq 0 ]]; then
  printf '%s\n' "[bike realtime reprocess] OK: $(date -Is)"
else
  printf '%s\n' "[bike realtime reprocess] FAILED(status=${status}): $(date -Is)"
fi

exit "${status}"
