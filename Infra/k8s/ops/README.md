# 관측 스택 (Grafana + Prometheus + node-exporter)

S15P21A104-341. 운영 대시보드 4장과 노드·배치 지표를 한곳에서 본다. 로컬 검증 스택
(`AI/validation/INFRA/observability-check/`, docker compose)을 k3s로 옮긴 것이다.

## 목적

| 보드 | uid | 내용 |
| --- | --- | --- |
| 모델 품질 (보드 ②) | `sumgil-model-quality` | 일별 채점·게이트 수락/거절 (ops API) |
| 파이프라인 건강 (보드 ③) | `sumgil-pipeline-health` | 러너 단계·textfile 잡 경과 (ops API + Prometheus) |
| Spark 잡 (보드 ⑤) | `sumgil-spark-jobs` | Spark run·검증 실패 (ops API) |
| 데이터 품질 (보드 ⑥) | `sumgil-data-quality` | availability 등 (ops API) |

보드 ①(서비스 지표)은 FE 옵션 C가 대체해 여기에 없다. 폴더는 "SUMGIL 운영".

## 구성도

```
브라우저 -> Ingress(nginx) /grafana -> grafana:3000 --+-- prometheus:9090 <- scrape(15s) -- node-exporter (DaemonSet, hostNetwork :9100, 노드마다 1개)
                                                      |                                         ^ textfile: 호스트 /var/lib/node_exporter/textfile
                                                      +-- ai:8000 (/ops/..., Infinity 플러그인)  <- AI 배치(host systemd)가 .prom 기록
```

클러스터 내부에서는 `/ai` 접두사가 없다(`http://ai:8000/ops/...`). `/ai`는 공개 Ingress에만 존재한다.

## 소유·경계 (CONTRACT.md 기준)

전부 Infra 소유다. ClusterRole·ClusterRoleBinding(클러스터 스코프), hostPath·hostNetwork(node-exporter),
local-path PVC가 있어 개발자가 아닌 Infra 리드가 apply한다. 대시보드 JSON은 AI가 정본을 관리하고
`sync-dashboards.sh`로 복사해 온다.

## 대시보드 JSON 정본

정본은 `AI/validation/INFRA/observability-check/grafana/dashboards/` 하나다. 이 디렉터리의
`grafana/dashboards/`는 **복사본**이다(kustomize는 루트 밖 파일을 읽지 못한다). 정본을 고친 뒤
`./sync-dashboards.sh`를 실행하고 같이 커밋한다. 복사본을 직접 고치지 않는다.
`AI/test/OPS/test_dashboard_consistency.py`가 복사본이 정본과 다르면 실패한다(CI).

## 적용 순서

```bash
cd Infra/k8s/ops
cp ops-secret.env.example ops-secret.env      # GF_SECURITY_ADMIN_PASSWORD 채우기 (gitignore: *-secret.env)
kubectl kustomize . > /dev/null               # 렌더 확인
kubectl apply -k .                            # 저장소 루트에서는 kubectl apply -k Infra/k8s/ops
kubectl -n prod get pods -l app.kubernetes.io/part-of=sumgil-ops -o wide
kubectl -n prod get ds node-exporter          # 노드 수만큼 READY
kubectl -n prod get ingress grafana
```

루트에 포함하려면 `Infra/k8s/kustomization.yaml`의 `resources`에 `ops/`를 추가한다(Infra 리드 결정 사항이라
이 변경에서는 넣지 않았다). 포함하더라도 `ops-secret.env`가 먼저 있어야 렌더된다.

## 서버 확인 체크리스트

1. `https://j15a104.p.ssafy.io/grafana/` 접속, `admin` + Secret 비밀번호로 로그인된다(익명 접근 불가).
2. Connections > Data sources 2개(`Prometheus`, `AI Ops API`) 모두 Save & test 성공.
3. 폴더 "SUMGIL 운영"에 보드 4장이 로드된다.
4. Prometheus에서 `node_filesystem_avail_bytes{mountpoint="/"}`에 노드별 값이 있다
   (`kubectl -n prod port-forward svc/prometheus 9090` 후 확인, targets 2개 UP).
5. textfile 지표 `sumgil_job_*`가 나온다. AI 배치(`crowd-score-daily.service`)는 worker 노드의 호스트 systemd에서
   `/var/lib/node_exporter/textfile`에 쓴다. 이 디렉터리는 node-exporter가 `DirectoryOrCreate`로 만들면 root 소유라,
   배치 실행 계정이 쓰려면 호스트에서 `sudo chown ubuntu /var/lib/node_exporter/textfile`을 한다.

## 자원 예산

| 구성 | 개수 | 요청(메모리/CPU) | 상한(메모리/CPU) |
| --- | --- | --- | --- |
| grafana | 1 | 128Mi / 100m | 256Mi / 500m |
| prometheus | 1 | 256Mi / 100m | 512Mi / 500m |
| node-exporter | 2 (노드마다) | 64Mi / 50m | 128Mi / 200m |
| 합계 | | 512Mi / 300m | 1024Mi / 1.4 CPU |

스토리지: grafana-data 2Gi + prometheus-data 5Gi (local-path, 노드 귀속).

## `honor_labels: true` 필수

textfile 지표는 자체 라벨 `job="crowd_*"`를 갖는다. 스크레이프 잡 라벨(`job=node`)과 충돌하면 기본 설정에서는
`exported_job`으로 밀려나 대시보드의 `{{job}}` 범례가 모두 `node`로 나온다. `prometheus/prometheus.yml`의
`honor_labels: true`를 지우지 않는다.

## 알려진 한계

- AI 배치가 호스트 systemd라 textfile 지표는 그 배치가 도는 노드(worker)의 hostPath에만 생긴다.
- Loki/Alloy(로그)는 2차 범위다.
- 접근은 Grafana 로그인만 쓴다. 익명 접근 없음, 가입 불가.
- Prometheus·Grafana 데이터는 노드 로컬 PVC라 노드 장애 시 사라질 수 있다(15일 보관).
- node-exporter는 hostNetwork 9100을 점유한다. 노드 방화벽(ufw)은 외부에 열지 않는다.

## 로컬 compose와의 차이

| 항목 | 로컬 compose | 서버 (이 디렉터리) |
| --- | --- | --- |
| Infinity / Prometheus URL | `host.docker.internal:8000` / `prometheus:9090` | `http://ai:8000`(`/ai` 없음) / `http://prometheus:9090` |
| Grafana 경로 | 루트 `:3000` | `/grafana` 서브패스(`GF_SERVER_*`) + Ingress |
| 관리자 비밀번호 | `admin` 하드코딩 | Secret `ops-secret` |
| 익명 접근 | 기본값 | `GF_AUTH_ANONYMOUS_ENABLED=false` 명시 |
| 스크레이프 대상 | static `node-exporter:9100` | `kubernetes_sd_configs`(endpoints)로 노드별 발견, `instance`=노드명 |
| node-exporter | 컨테이너, `./textfile` 픽스처 | DaemonSet hostNetwork/hostPID, 호스트 `/` + 실제 textfile 경로 |
| 볼륨 | docker volume | local-path PVC (2Gi/5Gi) |
| Prometheus 설정 갱신 | 재시작 | `--web.enable-lifecycle` (`POST /-/reload`) |
| PostgreSQL `pg-ro` | 없음 | 주석(보드 ①을 FE가 대체해 불필요) |
