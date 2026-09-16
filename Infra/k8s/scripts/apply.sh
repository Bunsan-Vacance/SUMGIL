#!/usr/bin/env bash
# 매니페스트 적용 (S15P21A104-124/126/127). EC2(노드1)에서 실행. 멱등(재실행 안전).
# 순서: Infra(네임스페이스·ingress-nginx·데이터 계층 PG·Redis·Kafka·Registry) → BE → FE.
# 전제: 데이터 자격증명은 Infra/k8s/prod/data-secret.env(data-secret.env.example 복사 후 DB_PASSWORD 기입).
#       비민감 앱 설정은 BE/k8s/prod/be-config.env(커밋됨).
#
# 사용법:
#   bash scripts/apply.sh
#
# 재실행: setup-insecure-registry.sh + build-push.sh 후 다시 실행하면 be·fe rollout까지 대기한다.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../.." && pwd)}"
INFRA_K8S="${REPO_ROOT}/Infra/k8s"
DATA_K8S="${INFRA_K8S}/prod"
BE_K8S="${REPO_ROOT}/BE/k8s/prod"
FE_K8S="${REPO_ROOT}/FE/k8s/prod"

if [ ! -f "${DATA_K8S}/data-secret.env" ]; then
  echo "Infra/k8s/prod/data-secret.env 없음. data-secret.env.example을 복사해 DB_PASSWORD를 기입하라." >&2
  exit 1
fi

echo "--- 클러스터 스코프 + 데이터 계층 적용 (네임스페이스·ingress-nginx·cert-manager·PG·Redis·Kafka·Registry) ---"
kubectl apply -k "${INFRA_K8S}" --server-side

echo "--- cert-manager 기동 대기 ---"
kubectl rollout status deployment/cert-manager -n cert-manager --timeout=240s
kubectl rollout status deployment/cert-manager-webhook -n cert-manager --timeout=240s
kubectl rollout status deployment/cert-manager-cainjector -n cert-manager --timeout=240s

echo "--- 데이터 rollout 대기 (postgres·redis·kafka·registry) ---"
kubectl rollout status statefulset/postgres -n "${REGISTRY_NAMESPACE}" --timeout=240s
kubectl rollout status statefulset/redis -n "${REGISTRY_NAMESPACE}" --timeout=180s
kubectl rollout status statefulset/kafka -n "${REGISTRY_NAMESPACE}" --timeout=300s
kubectl rollout status deployment/registry -n "${REGISTRY_NAMESPACE}" --timeout=180s

echo "--- TLS 인증서 발급 대기 (cert-manager · HTTP-01) ---"
kubectl wait --for=condition=Ready certificate/sumgil-tls -n "${REGISTRY_NAMESPACE}" --timeout=300s

image_ready() {
  curl -sf "${REGISTRY_ENDPOINT}/v2/$1/tags/list" 2>/dev/null | grep -q latest
}

if image_ready sumgil-be && image_ready sumgil-fe; then
  echo "--- 앱 적용 (BE → FE) ---"
  kubectl apply -k "${BE_K8S}" --server-side
  kubectl apply -k "${FE_K8S}" --server-side
  echo "--- app rollout 대기 (be·fe) ---"
  kubectl rollout status deployment/be -n "${REGISTRY_NAMESPACE}" --timeout=300s
  kubectl rollout status deployment/fe -n "${REGISTRY_NAMESPACE}" --timeout=300s
  echo "적용 완료. 확인: kubectl get all -n ${REGISTRY_NAMESPACE}"
else
  echo "이미지 미등록. 다음을 실행한 뒤 apply.sh를 재실행하라:"
  echo "  sudo bash ${SCRIPT_DIR}/setup-insecure-registry.sh   # 양쪽 노드"
  echo "  bash ${SCRIPT_DIR}/build-push.sh"
fi
