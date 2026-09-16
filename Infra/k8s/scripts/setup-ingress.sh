#!/usr/bin/env bash
# ingress-nginx 설치 (S15P21A104-124/126). node1(control-plane)에서 실행.
# k3s 내장 Traefik을 끄고 ingress-nginx를 깐다. 멱등.
#
#   sudo bash scripts/setup-ingress.sh
#
# 전제: k3s 가동 중. 이 스크립트는 node1의 /etc/rancher/k3s/config.yaml에 disable: traefik을 넣고 재시작한다.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../.." && pwd)}"
CFG=/etc/rancher/k3s/config.yaml

echo "--- 1. k3s config: traefik 비활성 ---"
mkdir -p /etc/rancher/k3s
touch "${CFG}"
if ! grep -q '^\s*-\s*traefik\s*$' "${CFG}" 2>/dev/null; then
  printf '\ndisable:\n  - traefik\n' >> "${CFG}"
  echo "disable: traefik 추가"
else
  echo "이미 비활성"
fi
cat "${CFG}"
systemctl restart k3s
echo "k3s 재시작. 노드 Ready 대기..."
for i in $(seq 1 30); do
  if kubectl get nodes 2>/dev/null | grep -q ' Ready '; then break; fi
  sleep 4
done

echo "--- 2. ingress-nginx apply ---"
kubectl apply -k "${REPO_ROOT}/Infra/k8s" --server-side
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=180s

echo "--- 3. 확인 ---"
kubectl get ingressclass
kubectl get pods -n ingress-nginx
kubectl get svc -n ingress-nginx
