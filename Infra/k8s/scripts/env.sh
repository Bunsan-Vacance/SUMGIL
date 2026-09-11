#!/usr/bin/env bash
# 공통 변수 단일 소스 (S15P21A104-125). 각 스크립트가 `source "$(dirname "$0")/env.sh"`로 불러 쓴다.
# 값은 환경변수로 덮어쓸 수 있다. 노드 IP는 tailscale 주소라 계정/노드 교체 시 여기만 바꾼다.
#
# 레지스트리는 클러스터 내장(NodePort). 노드 containerd가 이미지를 pull할 때
# 클러스터 DNS(*.svc.cluster.local)는 노드에서 해석되지 않으므로 NodePort 주소를 쓴다.

export REGISTRY_HOST="${REGISTRY_HOST:-100.103.156.53:30500}"
export REGISTRY_NAMESPACE="${REGISTRY_NAMESPACE:-prod}"
export REGISTRY_ENDPOINT="${REGISTRY_ENDPOINT:-http://${REGISTRY_HOST}}"
