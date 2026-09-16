# Infra/k8s/scripts — 스크립트 안내

> 노드 표기: **node1 = a104(CP)**, **node2 = a104a(worker)**.

## 언제·어디서

| 스크립트 | 언제 | 어디서 | root | 한 번/반복 |
|---|---|---|---|---|
| `sync-to-nodes.sh` | 배포 전 | 개발 PC | 아니오 | 반복 |
| `setup-node.sh` | 노드 준비 | node1·node2 각각 | 예 | 한 번 |
| `init-vpn.sh` | 클러스터 이전 | node1·node2 각각 | 예 | 한 번 |
| `init-k3s.sh` | 클러스터 | node1 | 예 | 한 번 |
| `init-k3s-worker.sh` | 클러스터 | node2 | 예 | 한 번 |
| `setup-ingress.sh` | 클러스터 | node1 | 예 | 한 번 |
| `apply.sh` | 배포 | node1 | 아니오 | 반복 (2단계) |
| `setup-insecure-registry.sh` | 배포 | node1·node2 각각 | 예 | 한 번 |
| `build-push.sh` | 배포 | node1 | 아니오 | 반복 |
| `env.sh` | — | (source 전용) | — | — |

## 실행 순서 (신규 구축)

```
[개발 PC]  sync-to-nodes.sh
[양쪽]     setup-node.sh
[양쪽]     init-vpn.sh
[node1]    init-k3s.sh
[node1]    cat /var/lib/rancher/k3s/server/node-token
[node2]    init-k3s-worker.sh
[node1]    setup-ingress.sh
[node1]    apply.sh
[양쪽]     setup-insecure-registry.sh
[node1]    build-push.sh
[node1]    apply.sh
```

## 환경변수

- `env.sh` — 공통 변수 단일 소스. `REGISTRY_HOST`(기본 `100.103.156.53:30500`), `REGISTRY_NAMESPACE`(prod), `REGISTRY_ENDPOINT`. 노드 IP가 바뀌면 여기와 각 `kustomization.yaml`의 `images.newName`을 고친다.
- `sync-to-nodes.sh` — `NODES`(기본 `a104 a104a`), `REMOTE_DIR`(기본 `sumgil`).
- `init-vpn.sh` — `TS_AUTHKEY`(필수, 시크릿), `TS_HOSTNAME`(node1/node2), `TAILSCALE_VERSION`(기본 1.102.2).
- `init-k3s-worker.sh` — `K3S_URL`(node1 VPN:6443), `K3S_TOKEN`(필수, 시크릿).

## 인자

- `init-k3s.sh`·`init-k3s-worker.sh` — `--node-ip`=VPN, `--flannel-iface ens5`, `--disable traefik`.
- `apply.sh` — `Infra/k8s`(네임스페이스·데이터 계층) → BE → FE 순서(데이터 rollout 후 앱). 이미지가 없으면 안내 후 종료. 전제: `Infra/k8s/prod/data-secret.env` + `BE/k8s/prod/be-secret.env`.
- `build-push.sh` — `bash build-push.sh`(둘 다) / `be` / `fe`. 태그는 체크아웃 SHA(재정의 `TAG=`)이며 `:latest`도 함께 push. 신규 배포는 `kustomize edit set image`로 SHA를 지정 후 apply.
- `sync-to-nodes.sh` — `BE/.env`·`BE/k8s/prod/be-secret.env`·`Infra/k8s/prod/data-secret.env` 제외, `be-*.env` 포함.

## 규칙

- 시크릿은 노드로 보내지 않는다 (`*-secret.env` 제외).
- 노드 스크립트는 root/sudo, `apply.sh`·`build-push.sh`는 일반 유저(docker 그룹).
- 네트워크 인자(flannel-iface·disable traefik) 변경은 k3s 재시작이 필요하다 (config.yaml).
