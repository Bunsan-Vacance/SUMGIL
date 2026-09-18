#!/usr/bin/env bash
# 노드 containerd insecure 레지스트리 등록 (S15P21A104-125). 양쪽 EC2에서 각각 실행.
# 평문 HTTP 레지스트리라 containerd에 명시해야 pull 된다. k3s 내장 containerd라
# /etc/rancher/k3s/registries.yaml에 둔다. 멱등(덮어쓰기).
#
# 사용법 (root 또는 sudo):
#   sudo bash scripts/setup/setup-insecure-registry.sh
#
# 전제: 레지스트리 Deployment 기동 후 (deploy/apply.sh).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../env.sh
source "${SCRIPT_DIR}/../env.sh"

mkdir -p /etc/rancher/k3s
cat > /etc/rancher/k3s/registries.yaml <<EOF
mirrors:
  "${REGISTRY_HOST}":
    endpoint:
      - "${REGISTRY_ENDPOINT}"
configs:
  "${REGISTRY_HOST}":
    tls:
      insecure_skip_verify: true
EOF

systemctl restart k3s-agent 2>/dev/null || systemctl restart k3s
echo "containerd 재시작 완료. 확인: crictl info"
