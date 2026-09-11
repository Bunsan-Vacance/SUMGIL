#!/usr/bin/env bash
# k3s worker (순서 1번, S15P21A104-124). node2에서 실행. VPN join 완료 전제.
#
# 사용법 (root 또는 sudo):
#   sudo K3S_URL=https://<node1-VPN-IP>:6443 K3S_TOKEN=<node-token> bash scripts/init-k3s-worker.sh
#
# 환경변수:
#   K3S_URL      필수. node1의 https://<VPN-IP>:6443.
#   K3S_TOKEN    필수. node1의 /var/lib/rancher/k3s/server/node-token 값 (시크릿扱い).
#   K3S_VERSION  선택. 기본값 v1.35.8+k3s1 (node1과 동일).
#
# 네트워크: node-ip=VPN(제어면), flannel-iface=ens5(VPC 오버레이). node1과 동일.

set -euo pipefail

K3S_VERSION="${K3S_VERSION:-v1.35.8+k3s1}"
: "${K3S_URL:?K3S_URL 필요 (예: https://100.x.y.z:6443)}"
: "${K3S_TOKEN:?K3S_TOKEN 필요 (node1 node-token 값)}"
NODE_IP="$(tailscale ip -4 | head -n 1)"
: "${NODE_IP:?tailscale IP 없음. init-vpn.sh 먼저 실행}"

curl -sfL https://get.k3s.io \
  | INSTALL_K3S_VERSION="${K3S_VERSION}" \
    K3S_URL="${K3S_URL}" K3S_TOKEN="${K3S_TOKEN}" sh -s - agent \
    --node-ip "${NODE_IP}" \
    --flannel-iface ens5
