# Infra/k8s/scripts — 스크립트 안내

> 이 디렉토리의 스크립트는 **실행 시점·위치**가 서로 다르다. 하나로 합칠 수 없다 (순서 의존·재시작 필요 지점이 다름).
> 노드 표기: **node1 = a104(CP)**, **node2 = a104a(worker)**.

## 한눈에

| 스크립트 | 언제 | 어디서 | root | 한 번/반복 |
|---|---|---|---|---|
| `sync-to-nodes.sh` | 배포 전 | **개발 PC** | 아니오 | 반복 |
| `setup-node.sh` | 노드 준비 | node1·node2 각각 | **예** | 한 번 |
| `init-vpn.sh` | 클러스터 이전 | node1·node2 각각 | **예** | 한 번 |
| `init-k3s.sh` | 클러스터 | **node1** | **예** | 한 번 |
| `init-k3s-worker.sh` | 클러스터 | **node2** | **예** | 한 번 |
| `setup-ingress.sh` | 클러스터 | **node1** | **예** | 한 번 |
| `apply.sh` | 배포 | node1 | 아니오 | 반복 (2단계) |
| `setup-insecure-registry.sh` | 배포 | node1·node2 각각 | **예** | 한 번 |
| `build-push.sh` | 배포 | node1 | 아니오 | 반복 |
| `env.sh` | — | (source 전용) | — | — |

## 실행 순서 (신규 구축 기준)

```
[개발 PC]  sync-to-nodes.sh
[양쪽]     setup-node.sh              # ufw off, docker insecure, docker 그룹
[양쪽]     init-vpn.sh                # tailscale join
[node1]    init-k3s.sh                # control-plane
[node1]    cat /var/lib/rancher/k3s/server/node-token
[node2]    init-k3s-worker.sh         # worker join
[node1]    setup-ingress.sh           # ingress-nginx
[node1]    apply.sh                   # 1차: namespace + registry·postgres·redis
[양쪽]     setup-insecure-registry.sh # containerd insecure 등록
[node1]    build-push.sh              # 이미지 빌드·push
[node1]    apply.sh                   # 2차: be·fe rollout
```

## 개별 설명

### `env.sh` (source 전용, 직접 실행 안 함)
- 공통 변수의 단일 소스. 다른 스크립트가 `source "$(dirname "$0")/env.sh"`로 불러 쓴다.
- `REGISTRY_HOST`(기본 `100.103.156.53:30500`), `REGISTRY_NAMESPACE`(prod), `REGISTRY_ENDPOINT`.
- 노드 IP가 바뀌면 여기(그리고 각 `kustomization.yaml`의 `images.newName`)를 고친다.

### `sync-to-nodes.sh` (개발 PC)
- `project/`에서 실행. Infra·BE·FE 소스를 `~/sumgil/`로 복사.
- **시크릿은 보내지 않는다** (`BE/.env`, `BE/k8s/prod/.env.secret` 제외). `config.env`는 비민감이라 포함.
- 환경변수: `NODES`(기본 `a104 a104a`), `REMOTE_DIR`(기본 `sumgil`).

### `setup-node.sh` (양쪽, root)
- ufw 비활성(오버레이 VXLAN이 VPC를 타므로 켜면 노드 간 파드 통신이 막힘).
- 호스트 docker에 insecure 레지스트리 등록 + 사용자를 docker 그룹에 추가(재로그인 후 반영).

### `init-vpn.sh` (양쪽, root)
- tailscale 설치·join. headless(`--authkey`).
- 환경변수: `TS_AUTHKEY`(필수, 시크릿), `TS_HOSTNAME`(node1/node2), `TAILSCALE_VERSION`(기본 1.102.2).

### `init-k3s.sh` / `init-k3s-worker.sh` (node1 / node2, root)
- k3s server / agent 설치.
- 핵심 인자: `--node-ip`=VPN(제어면), `--flannel-iface ens5`(오버레이 VPC), `--disable traefik`.
- worker는 `K3S_URL`(node1 VPN:6443)·`K3S_TOKEN`(필수, 시크릿)을 받는다.

### `setup-ingress.sh` (node1, root)
- k3s `config.yaml`에 `disable: traefik`을 넣고 재시작 → `Infra/k8s`(ingress-nginx) apply.
- Ingress 컨트롤러를 ingress-nginx로 고정한다 (팀 원안·기존 패턴과 일치, k3s 기본 Traefik 대체).

### `apply.sh` (node1, 반복)
- 2단계 멱등. `Infra/k8s/namespaces`(클러스터 스코프) → BE → FE 순서로 apply.
- 이미지가 없으면 안내하고 종료. 있으면 be·fe rollout까지 대기.
- 전제: `BE/k8s/prod/.env.secret` 존재.

### `setup-insecure-registry.sh` (양쪽, root)
- 노드 containerd에 평문 HTTP 레지스트리를 등록(`/etc/rancher/k3s/registries.yaml`). containerd 재시작.
- 내장 레지스트리(평문)를 노드가 pull하려면 필요하다.

### `build-push.sh` (node1)
- BE·FE 이미지를 빌드해 내장 레지스트리로 push.
- 사용법: `bash build-push.sh`(둘 다) / `bash build-push.sh be`(BE만) / `fe`.

## 함정 (재발 방지)

- **시크릿**: `sync-to-nodes.sh`는 `.env.secret`을 보내지 않는다. 새 스크립트를 추가할 때도 시크릿 제외를 빠뜨리지 않는다.
- **순서**: `setup-node`·`setup-insecure-registry`는 k3s 이전/이후가 갈린다(재시작 대상이 다름). 합치지 않는다.
- **root**: node 스크립트는 root/sudo. `apply.sh`·`build-push.sh`는 일반 유저(docker 그룹).
- **k3s 재시작**: 네트워크 인자(flannel-iface·disable traefik)를 바꾸면 k3s 재시작이 필요하다. config.yaml로 반영한다.
