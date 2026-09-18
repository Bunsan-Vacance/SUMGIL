#!/usr/bin/env bash
# 노드 사전 설정 (S15P21A104-123/125). 양쪽 EC2에서 각각 실행. 멱등(재실행 안전).
#
#   sudo bash scripts/setup/setup-node.sh
#
# 하는 일:
#   1. ufw 정책 적용(활성 고정) — 외부 허용 22/80/443, 내부 VPC VXLAN 8472만 추가.
#      ufw disable 금지. 파드 오버레이(VXLAN, UDP 8472)가 VPC(ens5)를 타므로 내부 허용이 필요하다.
#   2. Docker insecure 레지스트리 등록 — 호스트 docker로 레지스트리에 push하기 위함.
#   3. build/push 사용자를 docker 그룹에 추가.
#
# 전제: env.sh의 REGISTRY_HOST.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../env.sh
source "${SCRIPT_DIR}/../env.sh"

TARGET_USER="${SUDO_USER:-ubuntu}"

echo "--- 1. ufw 정책(활성, 외부 22/80/443 + 내부 VXLAN) ---"
if command -v ufw >/dev/null 2>&1; then
  ufw default deny incoming
  ufw default allow outgoing
  ufw default allow routed
  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw allow from "${VPC_CIDR}" to any port 8472 proto udp comment 'flannel vxlan'
  ufw --force enable
  ufw status verbose | head -1
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
