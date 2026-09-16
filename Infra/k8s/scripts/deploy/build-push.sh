#!/usr/bin/env bash
# BE·FE 이미지 빌드·push (S15P21A104-125/210). EC2(노드1)에서 실행.
# 전제: 레지스트리 Deployment 기동(apply.sh), 노드 insecure 등록(setup-insecure-registry.sh).
#
# 사용법:
#   bash scripts/deploy/build-push.sh            # BE·FE 둘 다, 태그는 체크아웃 SHA
#   bash scripts/deploy/build-push.sh be         # BE만
#   TAG=latest bash scripts/deploy/build-push.sh # 구 latest 흐름 (호환용)
#
# 태그: TAG 미지정 시 체크아웃 short SHA. :latest도 함께 push해 기존 apply.sh 게이트와 호환한다.
# 신규 배포는 SHA를 쓴다 — `kustomize edit set image` 후 apply. 롤백은 이전 SHA로 같은 절차 반복.
#
# FE 빌드 인자 (Dockerfile 필수): VITE_API_BASE_URL·VITE_KAKAO_MAP_APP_KEY를 환경변수로 넘긴다.
# 비어 있으면 Dockerfile이 빠진 이름을 짚어서 실패한다.
#
# 환경변수: scripts/env.sh 참조. REPO_ROOT로 소스 위치 지정 가능.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../env.sh
source "${SCRIPT_DIR}/../env.sh"

REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../../.." && pwd)}"
TARGET="${1:-all}"
TAG="${TAG:-$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo latest)}"

build_push() {
  local name="$1" dir="$2"
  shift 2
  local ref="${REGISTRY_HOST}/${name}:${TAG}"
  echo "--- build ${name} (${ref}) ---"
  docker build "$@" -t "${ref}" "${dir}"
  docker push "${ref}"
  if [ "${TAG}" != "latest" ]; then
    docker tag "${ref}" "${REGISTRY_HOST}/${name}:latest"
    docker push "${REGISTRY_HOST}/${name}:latest"
  fi
  echo "✓ ${name} pushed (${TAG})"
}

if [ "${TARGET}" = "all" ] || [ "${TARGET}" = "be" ]; then
  build_push sumgil-be "${REPO_ROOT}/BE"
fi
if [ "${TARGET}" = "all" ] || [ "${TARGET}" = "fe" ]; then
  build_push sumgil-fe "${REPO_ROOT}/FE" \
    --build-arg "VITE_API_BASE_URL=${VITE_API_BASE_URL:-}" \
    --build-arg "VITE_KAKAO_MAP_APP_KEY=${VITE_KAKAO_MAP_APP_KEY:-}"
fi

echo "완료. 레지스트리 목록 확인: curl ${REGISTRY_ENDPOINT}/v2/_catalog"
