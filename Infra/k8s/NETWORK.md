# 클러스터 내부 네트워크 인벤토리 (S15P21A104-210)

> 단일 정본. Service 추가·포트 변경 시 이 표를 먼저 고친다.
> 노드 포트(ufw·NodePort 실측)는 `mgmt/ops/port-inventory.md`, 경계 계약은 `CONTRACT.md`.
> 네임스페이스: 앱·데이터 전부 `prod` (`ingress-nginx`·`cert-manager`는 각자 ns).
> 현행 실측 (2026-09-16): 위 표 전부 Ready. Ingress 80,443 양쪽. `sumgil-tls` Ready.

## DNS·포트표 (클러스터 내부 호출용)

| DNS | 포트 | 타입 | 호출원 | 비고 |
|---|---|---|---|---|
| `postgres:5432` | 5432 | ClusterIP | BE (`DB_URL`), AI | 인증 `data-secret` |
| `redis:6379` | 6379 | ClusterIP | BE (`REDIS_HOST`), AI 컨슈머 | 인증 없음 |
| `kafka:9092` | 9092 | ClusterIP | BE 수집기·컨슈머 (`KAFKA_BOOTSTRAP_SERVERS`) | advertised `kafka:9092`. 9093(controller)은 파드 내부만 |
| `registry:5000` | 5000 | ClusterIP | kubelet pull (클러스터 내부) | 노드에서는 DNS 불가 → 아래 NodePort 사용 |
| `be:8080` | 8080 | ClusterIP | Ingress `/api/` | 헬스 `/actuator/health` |
| `fe:80` | 80 | ClusterIP | Ingress `/` | 헬스 `/healthz` |
| `ai:8000` | 8000 | ClusterIP | (호출원 없음 — 뼈대) | 헬스 `/health`. Ingress 없음 |
| `grafana:3000` | 3000 | ClusterIP | Ingress `/grafana` | 헬스 `/grafana/api/health`. 로그인 필수 |
| `prometheus:9090` | 9090 | ClusterIP | Grafana | 헬스 `/-/healthy`. Ingress 없음 |
| `node-exporter:9100` | 9100 | headless | Prometheus | DaemonSet hostNetwork(노드 IP:9100). Ingress 없음 |

Service 없음 (headless Deployment): `be-collector`, `be-consumer` — 외부에서 붙을 포트 자체가 없음.

## 외부 진입

| 진입 | → | 비고 |
|---|---|---|
| `j15a104.p.ssafy.io:80/443` | ingress-nginx → 위 표 | TLS는 `sumgil-tls` 종결, 내부는 HTTP |
| `<node>:30500` | registry:5000 | NodePort 고정. 노드 docker push용 (VPN 경유) |
| `j15a104.p.ssafy.io/grafana` | ingress-nginx -> grafana:3000 | 서브패스 직접 처리(rewrite 없음). `ops/ingress.yaml` |

ingress-nginx LB NodePort(443→3xxxx·80→3xxxx)는 자동 할당이라 표에 고정하지 않는다. 실측치는 `mgmt/ops/port-inventory.md`.

## 로컬 개발 대조 (compose)

| 로컬 | 클러스터 | 비고 |
|---|---|---|
| `localhost:5432/6379/9092` | `postgres/redis/kafka` (포트 동일) | compose는 호스트 publish, 클러스터는 ClusterIP |
| BE `:8080`, FE `:5173`(주석) | `be:8080`, `fe:80` | FE는 클러스터에서 nginx 80 |

## 규칙 (AI 작업용)

1. Service 이름·포트는 고정값 취급. 바꾸면 이 표 + 호출측 env(`be-config.env` 등)를 **동시에** 고친다.
2. 새 Service 추가 시 이 표에 행 추가 (DNS·포트·호출원·헬스).
3. 노드에서 클러스터 DNS(`*.svc`)는 안 통한다. 노드→클러스터는 NodePort·고정 IP만 쓴다.
4. Kafka 외부 노출·파티션 변경은 별도 티켓 (현재 내부 전용·파티션 1).
