#!/usr/bin/env bash
# GitLab CI/CD 변수 등록 (S15P21A104-210). 값 있는 셸에서 1회 실행.
# 목록의 유일 원본은 *.env.example — 키 추가 시 example만 고치면 이 스크립트가 추종한다.
#
# 사용:
#   export DB_PASSWORD=... SEOUL_SUBWAY_KEY=... SEOUL_API_KEY=... SEOUL_BIKE_KEY=... \
#     KMA_API_KEY=... VITE_API_BASE_URL=... VITE_KAKAO_MAP_APP_KEY=...
#   bash Infra/k8s/scripts/register-gitlab-vars.sh            # 없으면 생성, 있으면 값 갱신
#   bash Infra/k8s/scripts/register-gitlab-vars.sh --check   # 등록 여부만 확인 (값 미출력)
#
# 전제: glab 인증済 (project Maintainer 이상 — 변수 쓰기 권한).
# 값은 masked+protected+main 스코프. 디버그 출력(set -x) 금지.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

collect_keys() {
  local f
  for f in \
    "${REPO_ROOT}/Infra/k8s/prod/data-secret.env.example" \
    "${REPO_ROOT}/BE/k8s/prod/be-secret.env.example"; do
    grep -v '^[[:space:]]*#' "$f" | grep -v '^[[:space:]]*$' | cut -d= -f1 | grep -v '^[[:space:]]*$'
  done
  echo "VITE_API_BASE_URL"
  echo "VITE_KAKAO_MAP_APP_KEY"
}

if [ "${1:-}" = "--check" ]; then
  existing=$(glab variable list 2>/dev/null | awk 'NR>2 {print $1}')
  missing=0
  for k in $(collect_keys); do
    if ! echo "$existing" | grep -qx "$k"; then
      echo "미등록: $k"
      missing=1
    fi
  done
  [ "$missing" -eq 0 ] && echo "7건 전부 등록済"
  exit "$missing"
fi

for k in $(collect_keys); do
  v="${!k:-}"
  if [ -z "$v" ]; then
    echo "$k 없음 또는 빈값. export 후 재실행." >&2
    exit 1
  fi
  if glab variable get "$k" >/dev/null 2>&1; then
    echo "$v" | glab variable update "$k" --masked --protected --scope main >/dev/null
    echo "updated $k"
  else
    echo "$v" | glab variable set "$k" --masked --protected --scope main >/dev/null
    echo "created $k"
  fi
done
echo "완료. 확인: glab variable list"
