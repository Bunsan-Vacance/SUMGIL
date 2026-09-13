#!/usr/bin/env bash
# DATA_ENGINE raw → interim 배치를 한 번에 실행한다.
#
# 기본은 dry-run이며, 실제 저장하려면 --yes를 명시한다.
set -uo pipefail

usage() {
  printf '%s\n' \
    "Usage:" \
    "  run_data_engine_batch.sh [--date YYYY-MM-DD] [--yes]" \
    "" \
    "Options:" \
    "  --date YYYY-MM-DD  배치 대상 날짜. 생략하면 각 배치 모듈의 기본값(오늘 KST)을 사용." \
    "  --yes              실제 interim parquet 저장. 생략하면 dry-run." \
    "  -h, --help         도움말 출력."
}

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

DATE_ARGS=()
WRITE_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --date)
      DATE_ARGS=(--date "$2")
      shift 2
      ;;
    --yes)
      WRITE_ARGS=(--yes)
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "알 수 없는 옵션: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

status=0

cd "${AI_ROOT}"

run_batch() {
  local title="$1"
  local batch_status
  shift

  printf '\n%s\n' "${title}"
  "$@"
  batch_status=$?
  if [[ "${batch_status}" -ne 0 ]]; then
    status=1
  fi
}

run_batch "[1/2] bike stock 5min batch" \
  "${PYTHON}" -m DATA_ENGINE.batch.build_bike_stock_5min \
    "${DATE_ARGS[@]}" \
    "${WRITE_ARGS[@]}"

run_batch "[2/2] weather nowcast feature batch" \
  "${PYTHON}" -m DATA_ENGINE.batch.build_weather_nowcast_features \
    "${DATE_ARGS[@]}" \
    "${WRITE_ARGS[@]}"

printf '\n'
if [[ "${status}" -eq 0 ]]; then
  printf '%s\n' "DATA_ENGINE batch OK"
else
  printf '%s\n' "DATA_ENGINE batch FAILED"
fi

exit "${status}"
