#!/usr/bin/env bash
# 노드 사전 설정 (S15P21A104-123/125). 양쪽 EC2에서 각각 실행. 멱등(재실행 안전).
#
#   sudo bash scripts/setup-node.sh
#
# 하는 일:
#   1. ufw 비활성 — k3s·tailscale 네트워킹과 충돌 방지. 외부 경계는 AWS SG가 담당.
#      파드 오버레이(VXLAN, UDP 8472)가 VPC(ens5)를 타므로 ufw를 켜면 노드 간 파드 통신이 막힌다.
#   2. Docker insecure 레지스트리 등록 — 호스트 docker로 레지스트리에 push하기 위함.
#   3. build/push 사용자를 docker 그룹에 추가.
#
# 전제: env.sh의 REGISTRY_HOST.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

TARGET_USER="${SUDO_USER:-ubuntu}"

echo "--- 1. ufw 비활성 ---"
if command -v ufw >/dev/null 2>&1; then
  ufw disable || true
  ufw status | head -1
else
  echo "ufw 없음, 건너뜀"
fi

echo "--- 2. Docker insecure 레지스트리 ---"
if command -v docker >/dev/null 2>&1; then
  mkdir -p /etc/docker
  cat > /etc/docker/daemon.json <<EOF
{
  "insecure-registries": ["${REGISTRY_HOST}"]
}
EOF
  systemctl restart docker
  systemctl is-active docker
else
  echo "docker 없음, 건너뜀"
fi

echo "--- 3. docker 그룹 ---"
if getent group docker >/dev/null 2>&1; then
  usermod -aG docker "${TARGET_USER}" || true
  echo "${TARGET_USER} -> docker 그룹 (재로그인 후 반영)"
fi

echo "완료."
