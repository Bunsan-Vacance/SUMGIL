#!/usr/bin/env bash
# GitLab protected 변수 → *-secret.env 렌더 (S15P21A104-210 ③).
# secretGenerator가 읽는 실파일을 만든다. 값은 커밋하지 않는다.
#
# 사용 (값이 있는 셸에서 — 로컬 또는 GitLab manual job):
#   export DB_PASSWORD=... SEOUL_SUBWAY_KEY=... SEOUL_API_KEY=... SEOUL_BIKE_KEY=... KMA_API_KEY=...
#   bash Infra/k8s/scripts/render-secrets.sh
#
# 결과: BE/k8s/prod/be-secret.env + Infra/k8s/prod/data-secret.env (권한 600).
# 전달: 노드로 scp 후 apply.sh (sync-to-nodes.sh는 이 파일을 tar에서 제외한다).
#   scp BE/k8s/prod/be-secret.env a104:~/sumgil/BE/k8s/prod/be-secret.env
#   scp Infra/k8s/prod/data-secret.env a104:~/sumgil/Infra/k8s/prod/data-secret.env
#
# 전제: envsubst (없으면 apk add gettext / apt install gettext).
# 디버그 출력(set -x)은 절대 켜지 않는다 — 값이 로그에 샌다.

set -euo pipefail

command -v envsubst >/dev/null 2>&1 || {
  echo "envsubst 없음. alpine: apk add gettext / debian: apt install gettext" >&2
  exit 1
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# $1=템플릿 $2=출력 $3...=필수 변수. 미정의·빈값이면 즉시 실패 (빈 비밀번호 배포 방지).
# 렌더 후 남은 $가 있으면 실패 — 변수명 오타는 envsubst가 조용히 빈값으로 두므로.
render() {
  local template="$1" output="$2"
  shift 2
  local var
  for var in "$@"; do
    if [ -z "${!var:-}" ]; then
      echo "${var} 없음 또는 빈값. export 후 재실행." >&2
      exit 1
    fi
  done
  envsubst < "${REPO_ROOT}/${template}" > "${REPO_ROOT}/${output}"
  if grep -q '\${' "${REPO_ROOT}/${output}"; then
    echo "렌더 잔재 \${...} 발견 (${output}). 템플릿 변수명 오타 확인." >&2
    rm -f "${REPO_ROOT}/${output}"
    exit 1
  fi
  chmod 600 "${REPO_ROOT}/${output}"
  echo "rendered ${output}"
}

render BE/k8s/prod/be-secret.env.template BE/k8s/prod/be-secret.env \
  SEOUL_SUBWAY_KEY SEOUL_API_KEY SEOUL_BIKE_KEY KMA_API_KEY
render Infra/k8s/prod/data-secret.env.template Infra/k8s/prod/data-secret.env \
  DB_PASSWORD
