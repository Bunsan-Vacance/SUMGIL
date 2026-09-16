#!/usr/bin/env bash
# BE·FE 이미지 빌드·push (S15P21A104-125). EC2(노드1)에서 실행. 멱등(재실행 시 최신으로 덮음).
# 전제: 레지스트리 Deployment 기동(apply.sh), 노드 insecure 등록(setup-insecure-registry.sh).
#
# 사용법:
#   bash scripts/build-push.sh            # BE·FE 둘 다
#   bash scripts/build-push.sh be         # BE만
#
# 환경변수: scripts/env.sh 참조. REPO_ROOT로 소스 위치 지정 가능.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../.." && pwd)}"
TARGET="${1:-all}"

build_push() {
  local name="$1" dir="$2"
  local ref="${REGISTRY_HOST}/${name}:latest"
  echo "--- build ${name} (${ref}) ---"
  docker build -t "${ref}" "${dir}"
  docker push "${ref}"
  echo "✓ ${name} pushed"
}

if [ "${TARGET}" = "all" ] || [ "${TARGET}" = "be" ]; then
  build_push sumgil-be "${REPO_ROOT}/BE"
fi
if [ "${TARGET}" = "all" ] || [ "${TARGET}" = "fe" ]; then
  build_push sumgil-fe "${REPO_ROOT}/FE"
fi

echo "완료. 레지스트리 목록 확인: curl ${REGISTRY_ENDPOINT}/v2/_catalog"
