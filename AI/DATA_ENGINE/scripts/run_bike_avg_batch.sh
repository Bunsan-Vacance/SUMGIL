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

is_supported_python() {
  "$1" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

python_version() {
  "$1" - <<'PY' 2>/dev/null
import sys
print(".".join(map(str, sys.version_info[:3])))
PY
}

PYTHON=""
PYTHON_CANDIDATES=(
  "${AI_ROOT}/.venv/bin/python"
  "${AI_ROOT}/.venv/Scripts/python.exe"
)

if command -v python3.12 >/dev/null 2>&1; then
  PYTHON_CANDIDATES+=("$(command -v python3.12)")
fi
if command -v python3.11 >/dev/null 2>&1; then
  PYTHON_CANDIDATES+=("$(command -v python3.11)")
fi
if command -v python3 >/dev/null 2>&1; then
  PYTHON_CANDIDATES+=("$(command -v python3)")
fi
if command -v python >/dev/null 2>&1; then
  PYTHON_CANDIDATES+=("$(command -v python)")
fi

for candidate in "${PYTHON_CANDIDATES[@]}"; do
  if [[ -x "${candidate}" ]] && is_supported_python "${candidate}"; then
    PYTHON="${candidate}"
    break
  fi
done

if [[ -z "${PYTHON}" ]]; then
  printf '%s\n' "FAIL Python 3.10+ executable not found."
  printf '%s\n' "Checked candidates:"
  for candidate in "${PYTHON_CANDIDATES[@]}"; do
    if [[ -x "${candidate}" ]]; then
      printf '  - %s (version: %s)\n' "${candidate}" "$(python_version "${candidate}")"
    else
      printf '  - %s (not executable or missing)\n' "${candidate}"
    fi
  done
  printf '%s\n' "Create an AI venv with Python 3.10+ first, then rerun this script."
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
