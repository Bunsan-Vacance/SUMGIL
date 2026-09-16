#!/usr/bin/env bash
# VPN join (순서 0번, S15P21A104-123). 양쪽 EC2에서 각각 실행한다.
# 인바운드 포트 오픈 불필요. outbound TCP 443 + UDP면 동작한다.
#
# 사용법 (root 또는 sudo):
#   sudo TS_AUTHKEY=tskey-... TS_HOSTNAME=node1 bash scripts/init-vpn.sh
#
# 환경변수:
#   TS_AUTHKEY         필수. 관리 콘솔 발급 (reusable + pre-approved 권장). 값은 별도 채널.
#   TS_HOSTNAME        선택. 기본값은 hostname. 노드 구분되게 node1/node2 권장.
#   TAILSCALE_VERSION  선택. 기본값 1.102.2 (착수 시점 재확인). 비우면 stable 최신.

set -euo pipefail

TS_HOSTNAME="${TS_HOSTNAME:-$(hostname)}"
TAILSCALE_VERSION="${TAILSCALE_VERSION:-1.102.2}"
: "${TS_AUTHKEY:?TS_AUTHKEY 필요 (관리 콘솔 발급, reusable + pre-approved 권장)}"

if ! command -v tailscale >/dev/null 2>&1; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi

if [ -n "${TAILSCALE_VERSION}" ]; then
  apt-get install -y --allow-downgrades "tailscale=${TAILSCALE_VERSION}"
fi

tailscale up --authkey="${TS_AUTHKEY}" --hostname="${TS_HOSTNAME}"

echo "--- tailnet IP ---"
tailscale ip -4
echo "--- 연결 상태 (direct/relay 확인) ---"
tailscale status
