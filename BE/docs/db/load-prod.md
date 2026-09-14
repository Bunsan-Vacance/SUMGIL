# prod 정적 데이터 적재 (S15P21A104-167)

> 로컬 적재(`load-subway.md` · `load-bus-bike.md` · `load-congestion.md`)와 **같은 로더를 같은 명령으로** 돌린다.
> 다른 건 접속 경로 하나뿐이다 — prod Postgres 가 ClusterIP 전용이라 노드를 거쳐 터널을 뚫는다.
> 이 문서는 그 경로와, 그 과정에서 걸리는 함정을 다룬다.

## 1. 왜 터널인가

prod Postgres 는 `ClusterIP` 로만 떠 있어 클러스터 밖에서 직접 못 붙는다. 노드에는 붙는다(kube-proxy 가 ClusterIP 를 노드 네트워크에서 라우팅한다). 그래서 **노드를 경유해 로컬 포트로 끌어온다.**

k8s API(6443)로 `kubectl port-forward` 를 쓰는 길은 이 환경에서 막혀 있다 — 노드 `ufw` 가 외부에 `22/80/443` 만 열고, API 서버는 VPN 주소에 바인딩돼 인증서(`--tls-san`)도 그 주소로 발급됐다. 로컬 PC 에 kubeconfig 를 가져와도 닿지 않는다. **SSH(22)만 열려 있으므로 SSH 터널이 유일하게 단순한 길이다.**

```
로컬 PC :15432  ──ssh -L──▶  노드(j15a104)  ──ClusterIP──▶  postgres:5432 (prod)
```

## 2. 절차

### 2-1. 터널

```bash
PEM=<팀 pem 경로>            # 예: ~/Desktop/J15A104T.pem
NODE=ubuntu@j15a104.p.ssafy.io

# postgres ClusterIP 확인 (노드에서 k3s 가 kubeconfig 를 들고 있어 sudo kubectl 이 바로 된다)
ssh -i "$PEM" "$NODE" 'sudo kubectl get svc postgres -n prod -o jsonpath="{.spec.clusterIP}"'
# → 10.43.53.186 (2026-09-14. 서비스를 다시 만들면 바뀐다 — 매번 확인한다)

ssh -i "$PEM" -f -N -o ExitOnForwardFailure=yes -L 15432:<ClusterIP>:5432 "$NODE"
# 확인
bash -c 'cat < /dev/null > /dev/tcp/127.0.0.1/15432' && echo OK
```

끝나면 닫는다: `pkill -f "15432:"`

### 2-2. 접속 정보

`DB_PASSWORD` 는 데이터 계층이 소유한 Secret 에 있다(`Infra/k8s/CONTRACT.md` 4절). **셸 변수로만 받고 파일에 쓰거나 출력하지 않는다.**

```bash
export DB_URL=jdbc:postgresql://127.0.0.1:15432/sumgil
export DB_USERNAME=sumgil
export DB_PASSWORD=$(ssh -i "$PEM" "$NODE" \
  'sudo kubectl get secret data-secret -n prod -o jsonpath="{.data.DB_PASSWORD}"' | base64 -d)
export REDIS_HOST=localhost REDIS_PORT=6379   # 로더는 안 쓰지만 컨텍스트가 요구한다
```

### 2-3. 사전 확인

적재 전에 두 가지를 본다.

```bash
# (1) 마이그레이션 버전이 로컬과 같은가 — 다르면 멈춘다. 로더는 스키마를 만들지 않는다
ssh -i "$PEM" "$NODE" 'sudo kubectl exec -n prod sts/postgres -- \
  psql -U sumgil -d sumgil -tAc "select version, success, description from flyway_schema_history order by installed_rank"'
# 2026-09-14 확인: 1|t|init · 2|t|widen source columns · 3|t|rail geometry (로컬과 동일)

# (2) 현재 행 수
ssh -i "$PEM" "$NODE" 'sudo kubectl exec -n prod sts/postgres -- \
  psql -U sumgil -d sumgil -tAc "select tablename, n_live_tup from pg_stat_user_tables order by tablename"'
```

### 2-4. 적재

```bash
cd BE
SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun --offline
```

기본 소스는 `subway,bus,bike,railgeometry,congestion` 전부다(`application-load.yml`). 골라 돌리려면 `--args='--load.sources=bus,bike'`.

`UpsertWriter` 는 멱등이라 중간에 끊겨도 다시 돌리면 된다. `prune=true` 가 기본인데 빈 DB 에서는 지울 게 없고, 재적재 때는 시각표가 덮는 노선에서 이번 실행에 없는 행을 지우는 의도된 동작이다.

### 2-5. 검증

```bash
# 행 수
ssh -i "$PEM" "$NODE" 'sudo kubectl exec -n prod sts/postgres -- \
  psql -U sumgil -d sumgil -tAc "select tablename, n_live_tup from pg_stat_user_tables order by tablename"'

# API (로컬 결과와 대조한다)
curl -s "https://j15a104.p.ssafy.io/api/stations/search?query=강남"
curl -s "https://j15a104.p.ssafy.io/api/bike-stations/nearby?lat=37.5006&lng=127.0364&radius=3000"
curl -s "https://j15a104.p.ssafy.io/api/routes/search?..."
```

### 2-6. BE 재기동 (경로 검색에 필수)

**적재만으로는 경로 검색이 살아나지 않는다.**

| 엔드포인트 | 데이터 출처 | 재기동 필요 |
| --- | --- | --- |
| `/api/stations/search` | `StationRepository` 직접 조회 | 아니오 — 적재 즉시 값이 나온다 |
| `/api/bike-stations/nearby` | `BikeStationRepository` 직접 조회 | 아니오 |
| `/api/routes/search` | `RouteGraphRegistry` 의 메모리 그래프 | **예** |

`RouteGraphRegistry` · `RailGeometryRegistry` 가 `@PostConstruct` 로 **기동 시 1회만** DB 를 읽어 그래프를 만든다. 적재 전에 뜬 파드는 빈 그래프를 들고 있다.

```bash
ssh -i "$PEM" "$NODE" 'sudo kubectl rollout restart deployment/be -n prod && \
  sudo kubectl rollout status deployment/be -n prod --timeout=300s'
```

`replicas: 2` 라 롤링으로 바뀌어 무중단이다. 매니페스트를 바꾸는 게 아니라 운영 명령이므로 배포 계약(`Infra/k8s/CONTRACT.md`)의 "`k8s/**` 는 플랫폼 소유"에 걸리지 않지만, **실행 후 리드에게 알린다**(S15P21A104-173 의 재배포 주의 항목과 같은 맥락).

CI/CD 는 재기동을 일으키지 않는다 — `.gitlab-ci.yml` 은 `lint`·`test` 뿐이고, `apply.sh` 는 `rollout status`(완료 대기)만 있지 `rollout restart` 가 없다. ArgoCD 는 매니페스트만 있고 설치되지 않았다(클러스터에 `argocd` 네임스페이스가 없다). 그래서 수동이다.

## 3. 함정

### 3-1. dry-run 은 빈 DB 에서 혼잡도 단계에 반드시 실패한다

```
ERROR 혼잡도 검증 오류: 적재되지 않은 대상을 target_id 로 사용: LINE 1008 2/0
java.lang.IllegalStateException: 혼잡도 검증 오류 29016건 — 적재하지 않습니다
```

혼잡도는 대상 존재 검증에 **DB 에 적재된** 역·노선을 쓴다(`MasterValidator.validateCongestion(rows, writer.existingStationIds(), writer.existingLineIds())`). dry-run 은 지하철을 쓰지 않으므로 역이 하나도 없고, 혼잡도 전 행(29,016)이 "적재되지 않은 대상"으로 걸린다. **결함이 아니라 순서 의존이고**, `StaticLoadRunner.loadCongestion` 주석에 이미 적혀 있다.

빈 DB 에서 dry-run 으로 파싱만 확인하려면 혼잡도를 뺀다.

```bash
SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun --offline \
  --args='--load.dry-run=true --load.sources=subway,bus,bike,railgeometry'
```

실제 적재는 지하철이 먼저 쓰이므로 전체 소스를 한 번에 돌려도 된다.

### 3-2. 프로파일을 잘못 고르면 로그가 안 보이거나 엉뚱한 DB 에 쓴다

- `logback-spring.xml` 은 `local`·`default`·`prod` 프로파일에만 콘솔 출력을 붙인다. **`load` 만 주면 로그가 한 줄도 안 나온다.**
- `local,load` 를 쓸 때 `application-local.yml`(Git 제외)이 있으면 **그 파일의 datasource 가 환경변수를 덮어써 로컬 DB 에 적재될 수 있다.** 적재 전에 그 파일이 없는지, 있다면 datasource 를 선언하지 않는지 확인한다. 확실히 하려면 `prod,load` 를 쓴다(`application-prod.yml` 은 없고 설정은 전부 환경변수라 덮어쓸 것이 없다. 대신 콘솔이 JSON 이다).

### 3-3. ClusterIP 는 고정이 아니다

`10.43.53.186` 은 2026-09-14 값이다. Service 를 지우고 다시 만들면 바뀌므로 터널을 열 때마다 조회한다.

## 4. 실행 기록

| 날짜 | 범위 | 결과 |
| --- | --- | --- |
| 2026-09-14 | 사전 확인 · dry-run(`subway,bus,bike,railgeometry`) | 터널·인증·Flyway 버전 일치 확인. 네 소스 파싱·검증 통과(혼잡도는 3-1 로 중단) |
| — | 전체 적재 | **미실행** |

적재 소요 시간은 실행 후 이 절에 **1회 측정치**로 적는다. 터널을 경유하므로 로컬 수치와 조건이 달라 비교 근거로 쓰지 않는다(`BE/docs/perf/README.md` 규약).
