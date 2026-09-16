#!/usr/bin/env bash
# BE/Infra Kafka topics를 AI consumer group으로 구독해 raw parquet으로 저장한다.
set -euo pipefail

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

cd "${AI_ROOT}"
exec "${PYTHON}" -m DATA_ENGINE.stream.kafka_consumer "$@"
