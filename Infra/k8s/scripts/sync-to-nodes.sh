#!/usr/bin/env bash
# 개발 PC(로컬)에서 실행 — 인프라 산출물 + BE/FE 빌드 소스를 EC2 노드로 동기화. 멱등.
# project/ 디렉토리에서 실행한다 (git-bash 등).
#
#   bash Infra/k8s/scripts/sync-to-nodes.sh
#
# 환경변수:
#   NODES        대상 (기본 "a104 a104a"), ssh config 호스트명
#   REMOTE_DIR   원격 위치 (기본 "sumgil")
#
# 노트: 이미지 빌드는 노드에서 하므로 BE/FE 소스가 필요하다. 시크릿(.env)은 제외한다.

set -euo pipefail

NODES="${NODES:-a104 a104a}"
REMOTE_DIR="${REMOTE_DIR:-sumgil}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
TARBALL="$(mktemp -t sumgil-sync.XXXXXX.tar.gz)"

cleanup() { rm -f "${TARBALL}"; }
trap cleanup EXIT

# preflight: ssh 별칭이 이 셸에서 해석되는지 (WSL vs Windows 회피). 실패 시 즉시 안내.
for node in ${NODES}; do
  if ! ssh -o BatchMode=yes -o ConnectTimeout=8 "${node}" true 2>/dev/null; then
    echo "ssh ${node} 실패. NODES의 별칭이 이 셸의 ~/.ssh/config에 있는지 확인하라." >&2
    echo "  현재 HOME=${HOME} · config=$HOME/.ssh/config" >&2
    exit 1
  fi
done

cd "${PROJECT_ROOT}"
# 시크릿은 절대 노드로 보내지 않는다 (BE/.env·BE/k8s/prod/.env.secret·Infra/k8s/prod/.env.secret). config.env는 비민감이라 포함.
tar czf "${TARBALL}" \
  --exclude='BE/.env' --exclude='BE/k8s/prod/.env.secret' --exclude='BE/k8s/prod/.env' \
  --exclude='Infra/k8s/prod/.env.secret' --exclude='Infra/k8s/prod/.env' \
  --exclude='BE/build' --exclude='BE/.gradle' --exclude='BE/logs' \
  --exclude='FE/node_modules' --exclude='FE/dist' \
  Infra/k8s BE FE

for node in ${NODES}; do
  echo "--- ${node} ---"
  scp -q "${TARBALL}" "${node}:/tmp/sumgil-sync.tar.gz"
  ssh "${node}" "mkdir -p ~/${REMOTE_DIR} && tar xzf /tmp/sumgil-sync.tar.gz -C ~/${REMOTE_DIR} && chmod +x ~/${REMOTE_DIR}/Infra/k8s/scripts/*.sh && echo synced"
done

echo "완료."
