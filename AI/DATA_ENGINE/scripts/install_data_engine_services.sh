#!/usr/bin/env bash
# DATA_ENGINE 수집기와 BIKE avg 배치의 systemd 유닛을 설치한다.
#
# 기본 동작은 서비스 파일 설치 + daemon-reload까지만 수행한다.
# 실제 자동 실행까지 한 번에 진행하려면 --enable-now를 명시한다.
set -euo pipefail

usage() {
  printf '%s\n' \
    "Usage:" \
    "  install_data_engine_services.sh [--repo-root PATH] [--venv-path PATH] [--enable-now]" \
    "" \
    "Options:" \
    "  --repo-root PATH   저장소 루트 경로. 기본값은 이 스크립트 기준으로 자동 계산." \
    "  --venv-path PATH   Python venv 경로. 기본값은 <repo-root>/AI/.venv." \
    "  --enable-now       systemd enable --now까지 수행." \
    "  -h, --help         도움말 출력."
}

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
if [[ "${SCRIPT_SOURCE}" == */* ]]; then
  SCRIPT_DIR="$(cd "${SCRIPT_SOURCE%/*}" && pwd)"
else
  SCRIPT_DIR="$(pwd)"
fi
AI_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
REPO_ROOT="$(cd "${AI_DIR}/.." && pwd)"
VENV_PATH="${AI_DIR}/.venv"
ENABLE_NOW=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      REPO_ROOT="$2"
      shift 2
      ;;
    --venv-path)
      VENV_PATH="$2"
      shift 2
      ;;
    --enable-now)
      ENABLE_NOW=1
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

if [[ ! -d "${REPO_ROOT}/AI" ]]; then
  echo "REPO_ROOT가 올바르지 않습니다: ${REPO_ROOT}/AI 를 찾지 못했습니다." >&2
  exit 1
fi

if [[ ! -x "${VENV_PATH}/bin/python" ]]; then
  echo "venv python을 찾지 못했습니다: ${VENV_PATH}/bin/python" >&2
  echo "먼저 AI 디렉터리에서 python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt 를 실행하세요." >&2
  exit 1
fi

if [[ ! -f "${REPO_ROOT}/AI/.env" ]]; then
  echo "경고: ${REPO_ROOT}/AI/.env 파일이 없습니다. 서비스 시작 전 API key를 설정해야 합니다." >&2
fi

mkdir -p "${REPO_ROOT}/AI/logs"

install_service() {
  local template_name="$1"
  local service_name="$2"
  local template_path="${REPO_ROOT}/AI/DATA_ENGINE/scripts/${template_name}"
  local tmp_path

  if [[ ! -f "${template_path}" ]]; then
    echo "서비스 템플릿을 찾지 못했습니다: ${template_path}" >&2
    exit 1
  fi

  tmp_path="$(mktemp)"
  sed \
    -e "s|<REPO_ROOT>|${REPO_ROOT}|g" \
    -e "s|<VENV_PATH>|${VENV_PATH}|g" \
    "${template_path}" > "${tmp_path}"

  sudo install -m 0644 "${tmp_path}" "/etc/systemd/system/${service_name}"
  rm -f "${tmp_path}"
  echo "installed: /etc/systemd/system/${service_name}"
}

install_service "bike-realtime-poller.service" "bike-realtime-poller.service"
install_service "weather-nowcast-poller.service" "weather-nowcast-poller.service"
# 143: D−1 승하차 수집은 폴러가 아니라 하루 두 번 oneshot — timer 로 띄운다.
install_service "subway-ridership-daily.service" "subway-ridership-daily.service"
install_service "subway-ridership-daily.timer" "subway-ridership-daily.timer"
install_service "bike-avg-batch.service" "bike-avg-batch.service"
install_service "bike-avg-batch.timer" "bike-avg-batch.timer"
# 245: CROWD 혼잡도 예측 배치 — crowd-batch-predict.timer 가 매일 09:30(Asia/Seoul)에 띄운다.
install_service "crowd-batch-predict.service" "crowd-batch-predict.service"
install_service "crowd-batch-predict.timer" "crowd-batch-predict.timer"

sudo systemctl daemon-reload

if [[ "${ENABLE_NOW}" -eq 1 ]]; then
  sudo systemctl enable --now bike-realtime-poller.service
  sudo systemctl enable --now weather-nowcast-poller.service
  sudo systemctl enable --now subway-ridership-daily.timer
  sudo systemctl enable --now bike-avg-batch.timer
  sudo systemctl enable --now crowd-batch-predict.timer
  sudo systemctl status --no-pager bike-realtime-poller.service
  sudo systemctl status --no-pager weather-nowcast-poller.service
  sudo systemctl list-timers --no-pager subway-ridership-daily.timer
  sudo systemctl list-timers --no-pager bike-avg-batch.timer
  sudo systemctl list-timers --no-pager crowd-batch-predict.timer
else
  cat <<'EOF'

서비스 파일 설치와 daemon-reload가 끝났습니다.
실제 시작은 아래 명령으로 진행하세요.

  sudo systemctl enable --now bike-realtime-poller.service
  sudo systemctl enable --now weather-nowcast-poller.service
  sudo systemctl enable --now subway-ridership-daily.timer
  sudo systemctl enable --now bike-avg-batch.timer
  sudo systemctl enable --now crowd-batch-predict.timer
  sudo systemctl status bike-realtime-poller.service
  sudo systemctl status weather-nowcast-poller.service
  sudo systemctl list-timers subway-ridership-daily.timer
  sudo systemctl list-timers bike-avg-batch.timer
  sudo systemctl list-timers crowd-batch-predict.timer
EOF
fi
