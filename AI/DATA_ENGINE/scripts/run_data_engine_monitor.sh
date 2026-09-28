#!/usr/bin/env bash
# DATA_ENGINE 수집 상태 점검을 한 번에 실행한다.
#
# 정상: freshness + partition count + consumer lag 모두 통과하면 exit 0.
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
WEATHER_MAX_AGE_MIN="${WEATHER_MAX_AGE_MIN:-90}"
WEATHER_MIN_COUNT="${WEATHER_MIN_COUNT:-1}"
PARTITION_HOURS="${PARTITION_HOURS:-1}"
BIKE_MIN_COUNT="${BIKE_MIN_COUNT:-10}"
SUBWAY_MAX_AGE_MIN="${SUBWAY_MAX_AGE_MIN:-10}"
SUBWAY_MIN_RUNS="${SUBWAY_MIN_RUNS:-30}"
# lag 판정은 실행 간 이력을 쓰므로 모니터를 15분보다 촘촘하게(예: 5분) 돌려야 한다.
LAG_WARN_MIN="${LAG_WARN_MIN:-5}"
LAG_FAIL_MIN="${LAG_FAIL_MIN:-15}"
# 운영 시간은 SUBWAY_OPERATING_START / SUBWAY_OPERATING_END(HH:MM) 환경변수로 바꾼다.
DISCORD_NOTIFY_ON_FAILURE="${DISCORD_NOTIFY_ON_FAILURE:-1}"

status=0
MONITOR_OUTPUT=""

cd "${AI_ROOT}"

append_output() {
  local text="$1"
  if [[ -z "${MONITOR_OUTPUT}" ]]; then
    MONITOR_OUTPUT="${text}"
  else
    MONITOR_OUTPUT="${MONITOR_OUTPUT}"$'\n'"${text}"
  fi
}

print_and_capture() {
  local text="$1"
  printf '%s\n' "${text}"
  append_output "${text}"
}

# Discord 알림에는 실패한 점검의 FAIL/WARN 줄만 담는다. 정상 줄까지 넣으면 2000자 제한에
# 걸려 뒤쪽(lag) 실패가 잘릴 수 있다. FAIL/WARN 줄이 없는 실패(예: 스크립트 예외)는 끝 10줄을 담는다.
ALERT_OUTPUT=""

append_alert() {
  local text="$1"
  if [[ -z "${ALERT_OUTPUT}" ]]; then
    ALERT_OUTPUT="${text}"
  else
    ALERT_OUTPUT="${ALERT_OUTPUT}"$'\n'"${text}"
  fi
}

run_check() {
  local title="$1"
  local output
  local check_status
  local key_lines
  shift

  print_and_capture ""
  print_and_capture "${title}"
  output="$("$@" 2>&1)"
  check_status=$?
  if [[ -n "${output}" ]]; then
    print_and_capture "${output}"
  fi
  if [[ "${check_status}" -ne 0 ]]; then
    status=1
    append_alert "${title}"
    key_lines="$(printf '%s\n' "${output}" | grep -E '^(FAIL|WARN)' || true)"
    if [[ -z "${key_lines}" ]]; then
      key_lines="$(printf '%s\n' "${output}" | tail -n 10)"
    fi
    append_alert "${key_lines}"
  fi
}

run_check "[1/3] collection freshness check" \
  "${PYTHON}" -m DATA_ENGINE.monitor.check_collection_freshness \
    --ai-root "${AI_ROOT}" \
    --bike-max-age-min "${BIKE_MAX_AGE_MIN}" \
    --weather-max-age-min "${WEATHER_MAX_AGE_MIN}" \
    --subway-max-age-min "${SUBWAY_MAX_AGE_MIN}"

run_check "[2/3] partition count check" \
  "${PYTHON}" -m DATA_ENGINE.monitor.check_partition_counts \
    --ai-root "${AI_ROOT}" \
    --hours "${PARTITION_HOURS}" \
    --bike-min-count "${BIKE_MIN_COUNT}" \
    --weather-min-count "${WEATHER_MIN_COUNT}" \
    --subway-min-runs "${SUBWAY_MIN_RUNS}"

run_check "[3/3] kafka consumer lag check" \
  "${PYTHON}" -m DATA_ENGINE.monitor.check_consumer_lag \
    --warn-min "${LAG_WARN_MIN}" \
    --fail-min "${LAG_FAIL_MIN}"

printf '\n'
if [[ "${status}" -eq 0 ]]; then
  print_and_capture "DATA_ENGINE monitor OK"
else
  print_and_capture "DATA_ENGINE monitor FAILED"
  if [[ "${DISCORD_NOTIFY_ON_FAILURE}" != "0" ]]; then
    "${PYTHON}" -m DATA_ENGINE.monitor.notify_discord \
      --message "${ALERT_OUTPUT}"
  fi
fi

exit "${status}"
