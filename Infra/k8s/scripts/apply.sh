#!/usr/bin/env bash
# 매니페스트 적용 (S15P21A104-124/126/127). EC2(노드1)에서 실행. 멱등(재실행 안전).
# 전제: 비민감은 BE/k8s/prod/config.env(커밋됨), 비밀은 BE/k8s/prod/.env.secret(.env.example 복사 후 DB_PASSWORD 기입).
#
# 순서 (2단계):
#   1) 1차 실행: 인프라(registry·postgres·redis) 기동 후, 이미지가 없으면 안내하고 종료.
#   2) setup-insecure-registry.sh + build-push.sh 실행 후 재실행: be·fe rollout까지 대기.
#
# 사용법:
#   bash scripts/apply.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../.." && pwd)}"
BE_K8S="${REPO_ROOT}/BE/k8s/prod"
FE_K8S="${REPO_ROOT}/FE/k8s/prod"

if [ ! -f "${BE_K8S}/.env.secret" ]; then
  echo "BE/k8s/prod/.env.secret 없음. .env.example을 복사해 DB_PASSWORD를 기입하라." >&2
  exit 1
fi

echo "--- 클러스터 스코프 적용 (네임스페이스, Infra 소유) ---"
kubectl apply -k "${REPO_ROOT}/Infra/k8s/namespaces" --server-side

echo "--- apply: BE(infra+app), FE ---"
kubectl apply -k "${BE_K8S}" --server-side
kubectl apply -k "${FE_K8S}" --server-side

echo "--- infra rollout 대기 (registry·postgres·redis) ---"
kubectl rollout status deployment/registry -n "${REGISTRY_NAMESPACE}" --timeout=180s
kubectl rollout status statefulset/postgres -n "${REGISTRY_NAMESPACE}" --timeout=180s
kubectl rollout status statefulset/redis -n "${REGISTRY_NAMESPACE}" --timeout=180s

image_ready() {
  curl -sf "${REGISTRY_ENDPOINT}/v2/$1/tags/list" 2>/dev/null | grep -q latest
}

if image_ready sumgil-be && image_ready sumgil-fe; then
  echo "--- app rollout 대기 (be·fe) ---"
  kubectl rollout status deployment/be -n "${REGISTRY_NAMESPACE}" --timeout=300s
  kubectl rollout status deployment/fe -n "${REGISTRY_NAMESPACE}" --timeout=300s
  echo "적용 완료. 확인: kubectl get all -n ${REGISTRY_NAMESPACE}"
else
  echo "이미지 미등록. 다음을 실행한 뒤 apply.sh를 재실행하라:"
  echo "  sudo bash ${SCRIPT_DIR}/setup-insecure-registry.sh   # 양쪽 노드"
  echo "  bash ${SCRIPT_DIR}/build-push.sh"
fi
