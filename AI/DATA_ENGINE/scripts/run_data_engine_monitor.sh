#!/usr/bin/env bash
# DATA_ENGINE 수집 상태 점검을 한 번에 실행한다.
#
# 정상: freshness + partition count 모두 통과하면 exit 0.
# 비정상: 하나라도 실패하면 모든 점검을 마친 뒤 exit 1.
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
  printf '%s\n' \
    "FAIL python executable not found: ${AI_ROOT}/.venv/bin/python, ${AI_ROOT}/.venv/Scripts/python.exe, or python3"
  exit 1
fi

BIKE_MAX_AGE_MIN="${BIKE_MAX_AGE_MIN:-10}"
WEATHER_MAX_AGE_MIN="${WEATHER_MAX_AGE_MIN:-20}"
PARTITION_HOURS="${PARTITION_HOURS:-1}"
BIKE_MIN_COUNT="${BIKE_MIN_COUNT:-10}"
WEATHER_MIN_COUNT="${WEATHER_MIN_COUNT:-5}"

status=0

cd "${AI_ROOT}"

run_check() {
  local title="$1"
  shift

  printf '\n%s\n' "${title}"
  "$@"
  local check_status=$?
  if [[ "${check_status}" -ne 0 ]]; then
    status=1
  fi
}

run_check "[1/2] collection freshness check" \
  "${PYTHON}" -m DATA_ENGINE.monitor.check_collection_freshness \
    --ai-root "${AI_ROOT}" \
    --bike-max-age-min "${BIKE_MAX_AGE_MIN}" \
    --weather-max-age-min "${WEATHER_MAX_AGE_MIN}"

run_check "[2/2] partition count check" \
  "${PYTHON}" -m DATA_ENGINE.monitor.check_partition_counts \
    --ai-root "${AI_ROOT}" \
    --hours "${PARTITION_HOURS}" \
    --bike-min-count "${BIKE_MIN_COUNT}" \
    --weather-min-count "${WEATHER_MIN_COUNT}"

printf '\n'
if [[ "${status}" -eq 0 ]]; then
  printf '%s\n' "DATA_ENGINE monitor OK"
else
  printf '%s\n' "DATA_ENGINE monitor FAILED"
fi

exit "${status}"
