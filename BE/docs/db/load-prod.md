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
# 2026-09-17 확인: 5까지 적용 완료 (+ 4|congestion level comment · 5|bike stock pred prediction source)
# 2026-09-18 확인: 6까지 적용 완료 (+ 6|bus route headway). 로더 기동 로그도 `Successfully validated 6 migrations`
#
# 로더도 Flyway 를 돌린다 — FlywayConfig 에 프로파일 제한이 없어 load 프로파일로 띄워도 기동 때 마이그레이션이 적용된다.
# 위 주석의 "로더는 스키마를 만들지 않는다" 는 코드와 다르다(2026-09-17 확인). 정책으로 읽어야 한다:
# 로더로 prod 스키마를 올리지 않는다. prod DB 에 마이그레이션이 적용됐는데 돌고 있는 파드 이미지에
# 그 파일이 없으면 다음 재시작 때 Flyway 검증이 실패해 앱이 뜨지 않기 때문이다.
# 따라서 순서는 항상 "이미지 배포 → 적재" 다. 실제 배포 절차와 주의점은 docs/db/load-bikepred.md "선행 배포".

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
# 행 수 (파드 이름을 직접 쓴다. sts/postgres 로는 psql 이 붙지 않았고, 열 이름은 relname 이다)
ssh -i "$PEM" "$NODE" 'sudo kubectl exec -n prod postgres-0 -- \
  psql -U sumgil -d sumgil -tAc "select relname, n_live_tup from pg_stat_user_tables order by relname"'

# API — **-k 가 필요하다.** 도메인 인증서가 교육기관 자체 서명이라 curl 이 기본값으로 거부한다
# (붙이지 않으면 exit 60 · status=000 으로 빈 응답처럼 보인다).
curl -sk "https://j15a104.p.ssafy.io/api/stations/search?query=강남"
curl -sk "https://j15a104.p.ssafy.io/api/bike-stations/nearby?lat=37.5006&lng=127.0364&radius=3000"
curl -sk "https://j15a104.p.ssafy.io/api/routes/search?originStationId=222&destStationId=151"
```

경로 검색의 역 ID 는 **먼저 역 검색으로 확인한다.** `station_id` 는 환승역이면 노선별 코드 중 작은 값이라
노선 번호로 짐작하면 틀린다 — 시청은 1·2호선 환승이라 2호선 번호 `201` 이 아니라 1호선 번호 **`151`** 이다
(`201` 로 부르면 `STATION_NOT_FOUND` 404). 체계는 `docs/db/load-subway.md` 참고.

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

`replicas: 1` 이라 재기동 중 잠깐 끊긴다. 매니페스트를 바꾸는 게 아니라 운영 명령이므로 그대로 실행한다.
단, 볼륨·네트워크·StatefulSet 같은 클러스터 자원은 함부로 손대지 않는다 (`Infra/k8s/` 소유).
Deployment·Service 같은 파트 매니페스트는 문서 갱신을 전제로 각 파트가 작성할 수 있다.

CI/CD 는 재기동을 일으키지 않는다 — CI 는 `lint`·`test`·매니페스트 검증뿐이고, `apply.sh` 는 `rollout status`(완료 대기)만 있지 `rollout restart` 가 없다. GitOps 미도입이라 전부 수동이다.

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

## 4. 실행 기록 (2026-09-14)

Flyway 는 `Successfully validated 3 migrations` · `Schema "public" is up to date. No migration necessary.` — 스키마를 건드리지 않았다.

| 표 | 행 수 | 적재 시간 |
| --- | --- | --- |
| `line` | 18 | 36 ms |
| `station` | 564 | 54 ms |
| `transfer_meta` | 199 | 17 ms |
| `edge_time` | 193,536 | 14,517 ms (BATCH) |
| `bus_route` | 718 | 51 ms |
| `bus_stop` | 13,099 | 892 ms |
| `bike_station` | 2,731 | 176 ms |
| `rail_node` | 1,652 | 106 ms |
| `rail_link_geometry` | 1,728 | 301 ms |
| `congestion` | 29,016 | 2,275 ms |
| **합계** | **243,261** | **32,691 ms** (파싱·검증 포함 전체) |

적재 후 `pg_stat_user_tables` 행 수가 위 표와 일치한다. `bike_stock_pred` 는 0 으로 남는다 — S15P21A104-172 범위다.
`prune` 은 빈 DB 라 삭제 0건. 경고는 로컬 적재와 같은 종류였다(좌표 다수결 대체 10건, 시각표 이상치 27건, 대여소 거치대수 불일치 233건 등).

**검증 결과**

| 확인 | 결과 |
| --- | --- |
| `GET /api/stations/search?query=강남` | 4행 (강남 2호선·신분당선, 강남구청 7호선·수인분당선) |
| `GET /api/bike-stations/nearby` (역삼 3km) | `ST-1896` 강남파이낸스센터앞 49.8 m 외 실제 값 |
| `GET /api/routes/search` 222→151 **재기동 전** | `data: []` |
| `GET /api/routes/search` 222→151 **재기동 후** | 강남 → 신사(신분당선) → 환승 → 을지로3가(3호선) → … → 시청, 22.5분, 경로 형상 포함 |

재기동 필요 범위가 2-6 절 표대로 갈리는 것이 실제로 확인됐다. 역 검색·대여소 조회는 적재 직후 값이 나왔고, 경로 검색만 `kubectl rollout restart` 뒤에 살아났다. 롤링 재시작이라 중단은 없었다.

**성능 수치에 대해.** 위 시간은 **1회 측정치라 `BE/docs/perf/README.md` 규약(워밍업 1회 + 5회 이상, median·p95)을 충족하지 않는다.** 기준선으로만 남기고 개선 근거로 인용하지 않는다. 특히 `edge_time` 13,332 행/초는 SSH 터널을 경유한 값이라 로컬 직결 수치와 **조건이 달라 비교 대상이 아니다** — 터널 오버헤드와 로더 성능이 섞여 있어 둘을 나란히 놓으면 잘못된 결론이 난다.

## 5. 부분 적재 기록 (전체 재적재가 아닌 것)

2절 절차 그대로, `--load.sources` 만 좁혀 돌린 기록이다. 상세는 각 문서에 있다.

| 날짜 | 대상 | 소스 인자 | 결과 | 선행 배포 | 상세 |
| --- | --- | --- | --- | --- | --- |
| 2026-09-17 | `bike_stock_pred` (172) | `bikepred` | 406,656 행 | V5 — 이미지 빌드 + `be-consumer`·`be` 재시작 | [load-bikepred.md](load-bikepred.md) |
| 2026-09-18 | `bus_route.headway_min` (228) | `busheadway` | 451 행 UPDATE · 값 있음 446 · 33 ms | V6 — 이미지는 09-17 빌드, `be-consumer` 09-17 · `be` 09-18 재시작 | [load-bus-bike.md](load-bus-bike.md) 배차간격 절 |

- `busheadway` 는 `bus_route` 에 UPDATE 만 하므로 `bus` 를 함께 돌릴 필요가 없다 — 마스터 718행은 09-14 적재분 그대로다.
- 둘 다 읽는 코드가 없거나(배차간격) Redis 를 먼저 보는(재고 예측) 열이라 적재 뒤 `be` 재기동은 필요 없었다. 2-6 절 표의 "메모리 그래프" 열(`edge_time` 등)이 바뀔 때만 재기동한다.
- 09-18 은 로컬 Redis 없이(Docker 미기동) 로더가 정상 기동했다 — `RedisConfig` 는 템플릿만 만들고 연결은 첫 사용 때라, 2-2 절의 `REDIS_HOST` 는 자리만 채우면 된다.
