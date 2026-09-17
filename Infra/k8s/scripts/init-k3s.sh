#!/usr/bin/env bash
# k3s control-plane (순서 1번, S15P21A104-124). node1에서 실행. VPN join 완료 전제.
# 내장 Traefik은 끄고 ingress-nginx를 쓴다 (S15P21A104-124/126). metrics-server·local-path는 내장 유지.
#
# 사용법 (root 또는 sudo):
#   sudo K3S_VERSION=v1.35.8+k3s1 bash scripts/init-k3s.sh
#
# 환경변수:
#   K3S_VERSION  선택. 기본값 v1.35.8+k3s1 (착수 시점 재확인).
#
# 네트워크 (평면 분리):
#   --node-ip = VPN 주소  → 제어면(API·etcd·kubelet)이 tailnet 위.
#   --flannel-iface ens5  → 파드 오버레이(VXLAN)는 VPC 사설망. MTU 8951, 대용량에 유리.
#   두 스위치는 독립이다. 관리만 VPN, 데이터는 VPC.
#
# ingress: --disable traefik. ingress-nginx는 `setup-ingress.sh`로 설치한다.

set -euo pipefail

K3S_VERSION="${K3S_VERSION:-v1.35.8+k3s1}"
NODE_IP="$(tailscale ip -4 | head -n 1)"
: "${NODE_IP:?tailscale IP 없음. init-vpn.sh 먼저 실행}"

curl -sfL https://get.k3s.io \
  | INSTALL_K3S_VERSION="${K3S_VERSION}" sh -s - server \
    --node-ip "${NODE_IP}" \
    --tls-san "${NODE_IP}" \
    --flannel-iface ens5 \
    --flannel-backend vxlan \
    --disable traefik \
    --write-kubeconfig-mode 644

kubectl get nodes -o wide
