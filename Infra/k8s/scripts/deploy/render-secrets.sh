#!/usr/bin/env bash
# GitLab protected 변수 → *-secret.env 렌더 (S15P21A104-210 ③).
# secretGenerator가 읽는 실파일을 만든다. 값은 커밋하지 않는다.
#
# 키 목록의 유일 원본은 *.env.example 이다. 스크립트가 example 키 × 환경변수 값으로
# 직접 렌더하므로 별도 템플릿이 필요 없다 (envsubst 불필요).
#
# 사용 (값이 있는 셸에서 — 로컬 또는 GitLab manual job):
#   export DB_PASSWORD=... SEOUL_SUBWAY_KEY=... SEOUL_API_KEY=... SEOUL_BIKE_KEY=... KMA_API_KEY=...
#   bash Infra/k8s/scripts/deploy/render-secrets.sh
#
# 결과: BE/k8s/prod/be-secret.env + Infra/k8s/prod/data-secret.env (권한 600).
# 전달: 노드로 scp 후 apply.sh (sync-to-nodes.sh는 이 파일을 tar에서 제외한다).
#   scp BE/k8s/prod/be-secret.env a104:~/sumgil/BE/k8s/prod/be-secret.env
#   scp Infra/k8s/prod/data-secret.env a104:~/sumgil/Infra/k8s/prod/data-secret.env
#
# 디버그 출력(set -x)은 절대 켜지 않는다 — 값이 로그에 샌다.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

# $1=키목록 파일(*.env.example) $2=출력. example 키마다 환경변수가 비어있지 않아야 한다.
render() {
  local keys_file="$1" output="$2"
  local keys var
  keys=$(grep -v '^[[:space:]]*#' "${REPO_ROOT}/${keys_file}" | grep -v '^[[:space:]]*$' | cut -d= -f1 | grep -v '^[[:space:]]*$')
  if [ -z "${keys}" ]; then
    echo "키 없음: ${keys_file}" >&2
    exit 1
  fi
  local tmp
  tmp=$(mktemp)
  for var in ${keys}; do
    if [ -z "${!var:-}" ]; then
      echo "${var} 없음 또는 빈값. export 후 재실행." >&2
      rm -f "${tmp}"
      exit 1
    fi
    printf '%s=%s\n' "${var}" "${!var}" >> "${tmp}"
  done
  chmod 600 "${tmp}"
  mv "${tmp}" "${REPO_ROOT}/${output}"
  echo "rendered ${output}"
}

render BE/k8s/prod/be-secret.env.example BE/k8s/prod/be-secret.env
render Infra/k8s/prod/data-secret.env.example Infra/k8s/prod/data-secret.env
