# Infra

**스택** AWS EC2 · k3s(Kubernetes) · Kustomize

배포 환경 구성과 컨테이너 오케스트레이션을 담당한다. 1차 배포는 EC2 2대에 k3s 클러스터를 올려 운영한다.

---

## 현재 상태

**1차 배포 완료 (2026-09-11).** EC2 2대(a104 = control-plane, a104a = worker)에 k3s를 올리고 `prod` 네임스페이스에 BE·FE·Postgres·Redis·내장 레지스트리를 배치했다. 도메인(`j15a104.p.ssafy.io`) 경유 `/`→FE·`/api/`→BE 라우팅이 동작한다.

| 영역 | 위치 | 상태 |
| --- | --- | --- |
| 클러스터 스코프 매니페스트·스크립트 | `k8s/` | 운영 중 (Kustomize) |
| 네임스페이스 (`prod`) | `k8s/namespaces/` | 운영 중 (클러스터 스코프, Infra 소유) |
| Ingress 컨트롤러 (nginx) | `k8s/ingress-nginx/` | 운영 중 (vendored v1.15.1) |
| 로컬 개발용 DB·캐시·버퍼 | `docker/docker-compose.yml` | postgres·redis·kafka 기동 가능 |
| 리버스 프록시 (구안) | `nginx/nginx.conf` | **미사용 (legacy)** — Ingress 객체 + ingress-nginx가 담당 |

## 디렉터리 구조

```
Infra/
├─ k8s/
│  ├─ kustomization.yaml      클러스터 스코프 루트
│  ├─ namespaces/             앱 네임스페이스 (prod) — 클러스터 스코프라 Infra 소유
│  ├─ ingress-nginx/          ingress 컨트롤러 매니페스트 (vendored)
│  └─ scripts/                부트스트랩·동기화·이미지 스크립트
│     ├─ init-vpn.sh          VPN join (순서 0)
│     ├─ init-k3s.sh          control-plane 설치 (disable traefik, flannel-iface ens5)
│     ├─ init-k3s-worker.sh   worker join
│     ├─ setup-ingress.sh     ingress-nginx 설치 (traefik 비활성)
│     ├─ setup-node.sh        ufw off · docker insecure (양쪽)
│     ├─ setup-insecure-registry.sh  노드 containerd 레지스트리 등록
│     ├─ apply.sh             매니페스트 적용·rollout (2단계 멱등)
│     ├─ build-push.sh        BE·FE 이미지 빌드·push
│     ├─ env.sh               레지스트리 주소 단일 소스
│     └─ sync-to-nodes.sh     로컬 → 노드 동기화 (dev PC에서)
├─ docker/
│  └─ docker-compose.yml      로컬 개발 (postgres · redis · kafka)
└─ nginx/
   └─ nginx.conf              (legacy)
```

- 앱 워크로드·DB 매니페스트는 각 파트에 있다: `BE/k8s/`, `FE/k8s/`.
- 이미지는 클러스터 내장 레지스트리(`NodePort 30500`)에 보관한다.

## 배포

전체 절차는 팀 문서가 아니라 개인 런북으로 관리한다. **핵심만 요약하면**:

```bash
# 개발 PC: 소스·산출물을 노드로 동기화
bash Infra/k8s/scripts/sync-to-nodes.sh

# 각 노드: 사전 설정 (ufw off, docker insecure)
sudo bash ~/sumgil/Infra/k8s/scripts/setup-node.sh

# node1: cluster / node2: worker  (VPN join 선행)
sudo bash ~/sumgil/Infra/k8s/scripts/init-k3s.sh
sudo K3S_URL=https://<node1-VPN-IP>:6443 K3S_TOKEN=<token> bash ~/sumgil/Infra/k8s/scripts/init-k3s-worker.sh
sudo bash ~/sumgil/Infra/k8s/scripts/setup-ingress.sh   # ingress-nginx

# 배포 (registry·DB 먼저 → 이미지 push → 앱 rollout)
bash ~/sumgil/Infra/k8s/scripts/apply.sh
bash ~/sumgil/Infra/k8s/scripts/build-push.sh
bash ~/sumgil/Infra/k8s/scripts/apply.sh
```

## 로컬 기동 (개발용)

```bash
docker compose -f Infra/docker/docker-compose.yml up -d postgres redis      # BE 개발
docker compose -f Infra/docker/docker-compose.yml up -d --wait kafka        # 수집기·스트림
```

Kafka 구성·검증 절차·함정은 [BE/docs/infra/kafka.md](../BE/docs/infra/kafka.md)에 있다.

## 라우팅 설계

ingress-nginx가 80 포트를 받아 경로로 갈라 보낸다. **Ingress는 앱별 소유** — 각 앱이 자기 경로만 선언한다.

| 경로 | 대상 | 소유 |
| --- | --- | --- |
| `/api/` | 백엔드 (`be:8080`) | `BE/k8s/prod/ingress.yaml` |
| `/` | 프론트엔드 (`fe:80`) | `FE/k8s/prod/ingress.yaml` |

- 호스트는 `j15a104.p.ssafy.io` 단일 (와일드카드 서브도메인 등록 불가). 서비스 추가는 경로로만.
- 외부 HTTPS는 상위에서 종료되고, 클러스터는 HTTP만 서빙한다.

## 네트워크

- **평면 분리**: 관리(제어: API·etcd·kubelet)=VPN(`--node-ip`), 데이터(파드 VXLAN 오버레이)=VPC(`--flannel-iface ens5`, 파드 MTU 8951).
- 외부 사용자 트래픽(80/443)은 공개 NIC로 직접 들어오며 VPN을 타지 않는다.
- 노드 `ufw`는 비활성. 외부 경계는 AWS SG(22/80/443/8080)가 담당한다.

## 작업 규칙

- **`.env`, `.env.secret`, `*.pem`, `*.key`는 절대 커밋하지 않는다.** `.gitignore`에 등록돼 있으나 `git add -f`로 우회하지 않도록 주의한다.
- **비민감 설정은 `config.env`(커밋), 비밀은 `.env.secret`(gitignore).** kustomize `configMapGenerator`/`secretGenerator`가 각각 ConfigMap(`be-config`)·Secret(`be-secret`)으로 만든다.
- **레지스트리는 클러스터 내장을 쓴다.** 이미지 주소는 `k8s/scripts/env.sh`가 단일 소스다.
- **EC2에서 데이터 포트를 외부로 공개하지 않는다.** 클러스터 안에서는 ClusterIP로만 노출한다.
- EC2 키페어·DB 접속 정보·VPN 인증키는 팀 내 별도 채널로 공유한다.
