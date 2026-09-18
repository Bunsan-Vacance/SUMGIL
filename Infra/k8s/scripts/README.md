# Infra/k8s/scripts — 스크립트 안내

> 노드 표기: **node1 = a104(CP)**, **node2 = a104a(worker)**.
> 현행 클러스터 (2026-09-16 재구축): be·collector·consumer·fe ×1, StS ×3, Ingress tls(80,443),
> sumgil-tls Ready (LE, 만료 12/15), be-config 단일(17키), 고아 CM·Secret 제거済.
> 저장소-클러스터 일치 확인済 (2026-09-16). 상세 AC 기록은 티켓 210 정의서.

## 구성 (`setup/` 최초 1회 vs `deploy/` 반복, `env.sh` 공용)

| 스크립트 | 언제 | 어디서 | root | 한 번/반복 |
|---|---|---|---|---|
| `setup/init-vpn.sh` | 클러스터 이전 | node1·node2 각각 | 예 | 한 번 |
| `setup/init-k3s.sh` | 클러스터 | node1 | 예 | 한 번 |
| `setup/init-k3s-worker.sh` | 클러스터 | node2 | 예 | 한 번 |
| `setup/setup-node.sh` | 노드 준비 | node1·node2 각각 | 예 | 한 번 |
| `setup/setup-ingress.sh` | 클러스터 | node1 | 예 | 한 번 |
| `setup/setup-insecure-registry.sh` | 배포 | node1·node2 각각 | 예 | 한 번 |
| `deploy/sync-to-nodes.sh` | 배포 전 | 개발 PC | 아니오 | 반복 |
| `deploy/render-secrets.sh` | 배포 전 | 값 있는 셸 | 아니오 | 반복 (로테이션 시) |
| `deploy/build-push.sh` | 배포 | node1 | 아니오 | 반복 |
| `deploy/apply.sh` | 배포 | node1 | 아니오 | 반복 (2단계) |
| `env.sh` | — | (source 전용) | — | — |

## 실행 순서 (신규 구축)

```
[개발 PC]  deploy/sync-to-nodes.sh
[양쪽]     setup/setup-node.sh
[양쪽]     setup/init-vpn.sh
[node1]    setup/init-k3s.sh
[node1]    cat /var/lib/rancher/k3s/server/node-token
[node2]    setup/init-k3s-worker.sh
[node1]    setup/setup-ingress.sh
[node1]    deploy/apply.sh
[양쪽]     setup/setup-insecure-registry.sh
[node1]    deploy/build-push.sh
[node1]    deploy/apply.sh
```

## 환경변수

- `env.sh` — 공통 변수 단일 소스. `REGISTRY_HOST`(기본 `100.103.156.53:30500`), `REGISTRY_NAMESPACE`(prod), `REGISTRY_ENDPOINT`. 노드 IP가 바뀌면 여기와 각 `kustomization.yaml`의 `images.newName`을 고친다.
- `deploy/sync-to-nodes.sh` — `NODES`(기본 `a104 a104a`), `REMOTE_DIR`(기본 `sumgil`).
- `setup/init-vpn.sh` — `TS_AUTHKEY`(필수, 시크릿), `TS_HOSTNAME`(node1/node2), `TAILSCALE_VERSION`(기본 1.102.2).
- `setup/init-k3s-worker.sh` — `K3S_URL`(node1 VPN:6443), `K3S_TOKEN`(필수, 시크릿).
- `deploy/render-secrets.sh` — GitLab protected 변수 → `*-secret.env` 렌더 (210③).
  필요 변수: `DB_PASSWORD`·`SEOUL_SUBWAY_KEY`·`SEOUL_API_KEY`·`SEOUL_BIKE_KEY`·`KMA_API_KEY`
  (미정의·빈값·렌더 잔재 시 실패). 결과물은 노드로 scp 후 `apply.sh`. 디버그 출력 금지.

## 인자

- `setup/init-k3s.sh`·`setup/init-k3s-worker.sh` — `--node-ip`=VPN, `--flannel-iface ens5`, `--disable traefik`.
- `deploy/apply.sh` — `Infra/k8s`(네임스페이스·데이터 계층) → BE → FE 순서(데이터 rollout 후 앱). 이미지가 없으면 안내 후 종료. 전제: `Infra/k8s/prod/data-secret.env` + `BE/k8s/prod/be-secret.env`.
- `deploy/build-push.sh` — `bash build-push.sh`(둘 다) / `be` / `fe`. 태그는 체크아웃 SHA(재정의 `TAG=`)이며 `:latest`도 함께 push. 신규 배포는 `kustomize edit set image`로 SHA를 지정 후 apply.
- `deploy/sync-to-nodes.sh` — `BE/.env`·`BE/k8s/prod/be-secret.env`·`Infra/k8s/prod/data-secret.env` 제외, `be-*.env` 포함.

## 규칙

- 시크릿은 노드로 보내지 않는다 (`*-secret.env` 제외).
- 노드 스크립트는 root/sudo, `apply.sh`·`build-push.sh`는 일반 유저(docker 그룹).
- 네트워크 인자(flannel-iface·disable traefik) 변경은 k3s 재시작이 필요하다 (config.yaml).
