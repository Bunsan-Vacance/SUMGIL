#!/usr/bin/env bash
# BIKE avg predictor -> serving bike_stock_pred batch.
#
# This script writes the FastAPI serving artifacts:
#   data/BIKE/serving/bike_stock_pred_<timestamp>.parquet
#   data/BIKE/serving/bike_stock_pred_<timestamp>.csv
#   data/BIKE/serving/bike_stock_pred_<timestamp>.meta.json
set -uo pipefail

usage() {
  printf '%s\n' \
    "Usage:" \
    "  run_bike_avg_batch.sh [--artifact PATH] [--out-dir PATH]" \
    "" \
    "Options:" \
    "  --artifact PATH  models/BIKE/<artifact> directory. Defaults to latest artifact." \
    "  --out-dir PATH   Serving output directory. Defaults to app settings." \
    "  -h, --help       Show this help."
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
elif command -v python >/dev/null 2>&1; then
  PYTHON="$(command -v python)"
else
  printf '%s\n' \
    "FAIL python executable not found: ${AI_ROOT}/.venv/bin/python, ${AI_ROOT}/.venv/Scripts/python.exe, python3, or python"
  exit 1
fi

BATCH_ARGS=(--predictor avg)

while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact)
      BATCH_ARGS+=(--artifact "$2")
      shift 2
      ;;
    --out-dir)
      BATCH_ARGS+=(--out-dir "$2")
      shift 2
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

cd "${AI_ROOT}"

printf '%s\n' "[BIKE avg batch] start: $(date -Is)"
printf '%s\n' "[BIKE avg batch] python: ${PYTHON}"
printf '%s\n' "[BIKE avg batch] args: ${BATCH_ARGS[*]}"

"${PYTHON}" -m app.BIKE.pipeline.batch_predict "${BATCH_ARGS[@]}"
status=$?

if [[ "${status}" -eq 0 ]]; then
  printf '%s\n' "[BIKE avg batch] OK: $(date -Is)"
else
  printf '%s\n' "[BIKE avg batch] FAILED(status=${status}): $(date -Is)"
fi

exit "${status}"
