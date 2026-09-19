#!/usr/bin/env bash
# CROWD 혼잡도 예측 배치(app.CROWD.pipeline.batch_predict) 실행 스크립트.
#
# 이 스크립트가 만드는 산출물:
#   data/CROWD/serving/predictions_<날짜>.parquet + .meta.json
#   data/CROWD/serving/predictions_link_<날짜>.parquet
#   data/CROWD/serving/predictions_link_<날짜>_<HHMMSS>.csv   (BE 적재용)
set -uo pipefail

usage() {
  printf '%s\n' \
    "Usage:" \
    "  run_crowd_batch_predict.sh [--date YYYY-MM-DD ...] [--out-dir PATH] [--predictor KIND] [--no-link-table] [--no-recent]" \
    "" \
    "Options:" \
    "  --date YYYY-MM-DD   예측 대상 날짜(여러 번 지정 가능). 한 번이라도 주면 기본값(--today --tomorrow)을 붙이지 않는다." \
    "  --out-dir PATH      서빙 출력 디렉터리. 기본값은 앱 설정값." \
    "  --predictor KIND    예측기 종류(auto|lookup|lightgbm|dl|llm). 기본값은 라우팅(설정값)." \
    "  --no-link-table     링크(from/to) 표·BE CSV를 산출하지 않는다(기본은 --link-table로 산출한다)." \
    "  --no-recent         D−1 수집 파일을 이어붙이지 않는다(패널만 사용)." \
    "  -h, --help          도움말 출력."
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

DATE_ARGS=()
HAS_DATE=0
OUT_DIR=""
PREDICTOR=""
LINK_OPT="--link-table"
NO_RECENT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --date)
      DATE_ARGS+=(--date "$2")
      HAS_DATE=1
      shift 2
      ;;
    --out-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    --predictor)
      PREDICTOR="$2"
      shift 2
      ;;
    --no-link-table)
      LINK_OPT="--no-link-table"
      shift
      ;;
    --no-recent)
      NO_RECENT=1
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

BATCH_ARGS=()
if [[ "${HAS_DATE}" -eq 1 ]]; then
  BATCH_ARGS+=("${DATE_ARGS[@]}")
else
  BATCH_ARGS+=(--today --tomorrow)
fi
BATCH_ARGS+=("${LINK_OPT}")
if [[ -n "${OUT_DIR}" ]]; then
  BATCH_ARGS+=(--out-dir "${OUT_DIR}")
fi
if [[ -n "${PREDICTOR}" ]]; then
  BATCH_ARGS+=(--predictor "${PREDICTOR}")
fi
if [[ "${NO_RECENT}" -eq 1 ]]; then
  BATCH_ARGS+=(--no-recent)
fi

cd "${AI_ROOT}"

printf '%s\n' "[CROWD batch] start: $(date -Is)"
printf '%s\n' "[CROWD batch] python: ${PYTHON}"
printf '%s\n' "[CROWD batch] args: ${BATCH_ARGS[*]}"

"${PYTHON}" -m app.CROWD.pipeline.batch_predict "${BATCH_ARGS[@]}"
status=$?

if [[ "${status}" -eq 0 ]]; then
  printf '%s\n' "[CROWD batch] OK: $(date -Is)"
else
  printf '%s\n' "[CROWD batch] FAILED(status=${status}): $(date -Is)"
fi

exit "${status}"
