# 버스 정류소·노선, 따릉이 대여소 정적 적재 (S15P21A104-72)

> `bus_stop` · `bus_route` · `bike_station` 을 공공데이터에서 채우는 로더. 69 의 지하철 로더(`load-subway.md`)와 같은 골격(`load` 프로파일 · CsvTable · UpsertWriter)을 쓴다.
> 코드는 `com.ssafy.s15p21a104.load.{bus,bike}` + `MasterValidator`, 원천은 `src/main/resources/data/{bus,bike}/` (출처·열 설명은 각 폴더 README).

## 실행

```bash
# 1) DB 기동 (저장소 루트)
docker compose -f Infra/docker/docker-compose.yml up -d postgres

# 2) 적재 (BE 폴더). local 프로파일이 없으면 DB_URL·DB_USERNAME·DB_PASSWORD 환경변수로 대신한다
cd BE
SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun --args='--load.dry-run=true'            # 지하철·버스·따릉이 전부 파싱·검증만
SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun                                          # 전부 적재 (application-load.yml 기본 sources)
SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun --args='--load.sources=bus,bike'         # 마스터만
```

| 옵션 | 기본 | 뜻 |
| --- | --- | --- |
| `--load.sources` | `subway,bus,bike` | 적재 대상과 순서. 모르는 값은 경고 후 건너뜀 |
| `--load.dry-run` | false | DB 에 쓰지 않고 파싱 건수·대조·검증 결과만 출력 |
| `--load.region` | (전부) | **지하철 line_id 기준**이라 버스·따릉이에는 적용되지 않는다. 서비스 권역 확정 후 별도 파라미터가 필요하다 |

- 프로파일은 `local,load` 두 개를 함께 준다 (`logback-spring.xml` 이 `load` 단독에는 콘솔 출력을 붙이지 않는다).
- 멱등: 자연키 `ON CONFLICT DO UPDATE`, `updated_at` 은 실행 시각. 두 번 실행해도 건수가 같다.
- 검증 오류가 하나라도 있으면 그 원천은 아무것도 쓰지 않고 예외로 끝난다. 경고는 로그로만 남긴다. `좌표 없음` 경고는 한 줄로 묶는다.

## 2026-09-09 적재 결과 (로컬 postgres:16)

| 테이블 | 행 | 처리량 | 비고 |
| --- | --- | --- | --- |
| `bus_route` | 718 | 약 15,000 행/초 (50 ms) | 노선별 정류소 파일의 ROUTE_ID distinct. 노선명 충돌 0 |
| `bus_stop` | 13,099 | 약 45,000 행/초 (280~300 ms) | 위치정보 11,236 + 노선별 파일 보충 1,863 (경기 구간). 좌표 없음 0 |
| `bike_station` | 2,731 | 약 31,000 행/초 (88 ms) | bikeList 스냅샷(2026-09-09 11:09 KST, 3회 호출) 기준. 좌표·거치대수 없음 0 |

버스 검증·파싱 경고: 0건. 두 번 실행 후 건수 동일 (13,099 · 718 · 2,731).

따릉이 파일(OA-13252, 2026-06) 대조 결과 — 경고 3줄, 오류 0:

| 항목 | 건수 | 뜻 |
| --- | --- | --- |
| 대여소번호 일치 | 2,723 | 스냅샷 이름 접두어 = 파일 대여소번호. 접두어 없는 이름 0 |
| 스냅샷에만 | 8 | 파일 배포(6월) 뒤 신설: 3941, 4849, 4970, 5516, 5899, 5900, 6191, 6192 |
| 파일에만 | 66 | 스냅샷에 없음 — 폐쇄·휴점·이전으로 보이며 적재하지 않는다 |
| 거치대수 불일치 | 233 | 스냅샷 rackTotCnt ≠ 파일 LCD+QR. 스냅샷 값을 쓴다 (실시간 재고와 같은 체계) |

이름이 숫자·점으로 시작하는 대여소 4건(예: `4.19민주묘지역` 류)은 접두어를 뗀 뒤에도 남는 실제 이름이다.

## 배차간격 (S15P21A104-228, 2026-09-17)

`bus_route.headway_min` 을 채운다. 경로 탐색이 버스 대기시간을 계산할 근거가 없어 `BusEdgeBuilder` 가 모든 BUS 엣지의
`waitSec` 을 0 으로 두고 있었다 — 지하철은 `edge_time` 에 슬롯별 `wait_sec` 이 있는데 버스만 비어 있었다.
그래프가 `wait_sec = headway_min × 60 ÷ 2` 로 쓰는 것은 **A 파트 후속**이고 여기서는 표만 채운다.

```bash
# 1) 수집 (호출 178회. 실행 전 --dry-run 으로 호출 수를 확인한다)
node BE/scripts/data/bus-headway-fetch.mjs --dry-run
node BE/scripts/data/bus-headway-fetch.mjs

# 2) 적재 — bus 뒤에 와야 한다 (기존 bus_route 행을 UPDATE 한다)
cd BE
SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun --args='--load.sources=bus,busheadway'
```

### 원천과 값 규칙

원천은 **도착정보 API**(공공데이터포털 15000314)의 `term` 이다. 노선정보조회(15000193)는 우리 키로 안 열린다 —
401 `등록되지 않은 서비스키`. 포털은 서비스마다 활용신청이 따로다.

- **정적 값이다.** 2026-09-08 11:10 과 09-17 14:59 두 관측에서 14개 노선 전부 `term` 이 같았다.
- **시간대별로 갈리지 않는다.** 노선당 대표값 하나다. 그래프가 `headway ÷ 2` 로 쓰면 **첨두에는 과대추정, 한산할 때는 과소추정**이다.
- **0 은 NULL 이다.** "배차 0분" 이 아니라 "그 시각에 운행 중이 아니라 모른다" 는 뜻이다. 0 을 그대로 넣으면 대기시간이 0초가 되어 그 노선이 무조건 최단 경로로 뽑힌다.
- **첫차·막차는 CSV 에만 있고 적재하지 않는다.** 같은 응답에 `firstTm`·`lastTm` 이 오지만 위 두 관측에서 **12/14 노선이 몇 분씩 달라졌다** — 운행 기록을 반영해 갱신되는 값이라 정적 표에 넣으면 그날부터 낡는다. 쓰기로 정하면 재수집 없이 CSV 에서 꺼낸다.
- **INSERT 하지 않고 UPDATE 만 한다.** 응답에 우리 마스터(718 노선)에 없는 경기 노선이 섞여 오는데(1차 수집에서 278행) upsert 로 넣으면 `bus_route` 가 두 원천으로 갈라진다.

### 적재 결과 (로컬 postgres:16)

| 항목 | 값 |
| --- | --- |
| 수집 CSV | **451행** (`seoul-bus-headway_20260917.csv`) |
| 갱신 | **451행** — 마스터에 없는 노선 0 |
| 값 있음 | **446** · NULL **272** (718 노선 기준) |
| 표본 대조 | 741 = 10 · 705 = 16 · 703 = 20 · 571 = 11 (09-08 샘플과 동일) |
| 분포 | 최소 5분 · 중앙값 12분 · 최대 350분 |
| 적재 시간 | 12 ms (1회 측정치) |

### prod 적재 (2026-09-18)

선행으로 `be` 를 V6 포함 이미지로 재시작했다 — 어제는 `be-consumer` 만 새 이미지였다([load-bikepred.md](load-bikepred.md) "선행 배포" 의 둘째 주의).
함께 나간 것은 09-17 13:58 이후 병합분(190·192·193·194, 전우석 승인). 적재는 터널로 `--load.sources=busheadway` 만 돌렸다 —
`bus_route` 718행은 09-14 에 이미 있어 `bus` 를 다시 돌릴 이유가 없다([load-prod.md](load-prod.md) 5절).

| 항목 | 값 |
| --- | --- |
| 적재 전 | 718행 · `headway_min` 0 · Flyway 6 |
| 로그 | `원천 451 행 · 갱신 대상 451 · 값 있음 446 · 건너뜀 0` → `451 행 · 33 ms · 13,667 행/초` → 완료 55 ms |
| 적재 후 | 718행 · 값 있음 **446** · 0값 **0** |
| 표본 | 571(`100100084`)=11 · 705(`100100587`)=16 · 703(`116000006`)=20 · 741(`123000010`)=10 — 로컬과 동일 |
| 분포 | 최소 5 · 중앙값 12 · 최대 350 — 로컬과 동일 |

33 ms 는 SSH 터널 경유 **1회 측정치**다(perf 규약 미충족, 기준선 아님). 이 열을 읽는 코드가 아직 없어 `be` 재기동은 필요 없다 —
`BusEdgeBuilder` 가 쓰기 시작하면 그때 재기동한다.

### 718 중 451 만 받히는 이유 — 호출을 더 써도 안 된다

2026-09-17 에 **호출 525회**를 쓰며 확인했다. 나머지 267 개는 이 API 로 받을 수 없다.

| 이유 | 노선 | 근거 |
| --- | --- | --- |
| API 가 그 노선을 다루지 않음 | 115 | **이미 부른 정류소를 지나는데 응답에 없다.** 영등포11 이 지나는 샛강역1번출구(118000068)를 부르면 13개 노선이 오는데 영등포11 이 없다 |
| API 가 아는 정류소를 하나도 안 지남 | 152 | 마을버스 전용 정류소(`NODE_ID` 4~6자리가 `900`)만 운행. 그 정류소를 부르면 `headerCd 4 · itemList null` |

**"마을버스는 전부 안 된다" 가 아니다** — 받은 451 개에 마을버스(`routeType 4`)가 243 개 들어 있다. 큰 거점을 지나는 것들이다.

수집 스크립트가 옵션 넷을 갖는 이유가 이 시행착오다. `--dry-run`(호출 0회로 호출 수 확인), `--per-route`(노선당 정류소 1곳 — 기본 그리디는 큰 거점만 골라 짧은 노선이 빠진다), `--general-stops-only`(`900` 정류소 제외), `--limit`(전체를 쏘기 전 작게 시험).

> **헛돈 호출 347회.** 1차 178콜로 451개를 받은 뒤 2차(124콜)·3차(200콜)·4차 시험(20콜)이 전부 0개를 추가했다.
> 매번 "정류소를 바꾸면 되겠지" 라는 가정으로 쐈고 세 번 다 틀렸다. **원인 조사는 호출 0회로 가능했다** —
> 못 받은 노선이 이미 부른 정류소를 지나는지 세면 115개가 나온다. 1차 직후에 했으면 347회를 아꼈다.

## 데이터 흐름

```
data/bus/seoul-bus-stops (위치정보, 정본) ────────┐
                                                 ├─▶ BusStopParser ─▶ BusStopRow ──┐
data/bus/seoul-bus-route-stops (노선×경유 정류소) ─┤   (파일에 없는 NODE_ID 보충)      ├─▶ MasterValidator.validateBus ─▶ UpsertWriter (bus_route → bus_stop)
                                                 └─▶ BusRouteParser ─▶ BusRouteRow ─┘

data/bike/seoul-bike-stations-live (bikeList 스냅샷, 정본) ─▶ BikeStationParser ─▶ BikeStationRow ─▶ MasterValidator.validateBike ─▶ UpsertWriter (bike_station)
data/bike/seoul-bike-stations (파일, OA-13252) ────────────▶   └ 대여소번호로 대조 → 경고·CrossCheck 집계
```

## 식별자·값 규칙

| 컬럼 | 값 | 근거 |
| --- | --- | --- |
| `bus_stop.stop_id` | 원천 `NODE_ID` (9자리) | 버스 도착정보 API `getLowArrInfoByStId` 의 `stId` 와 같은 체계 (샘플 111000012 확인) |
| `bus_stop.lat/lng` | `Y좌표` / `X좌표` (WGS84 도) | 위치정보 파일 우선, 없으면 노선별 파일 값. 원천에 없으면 null |
| `bus_route.route_id` | 원천 `ROUTE_ID` (9자리) | 도착정보 API `busRouteId` 와 같은 체계 (샘플 100000028 = 새벽A741) |
| `bike_station.rental_id` | bikeList `stationId` (`ST-4` 형태) | API 명세 `rentalId` 예시 `ST-1577`, Redis 키 `bike:stock:{rentalId}` 와 같은 값. 2주차 수집기가 변환 없이 쓴다 |
| `bike_station.name` | `stationName` 에서 번호 접두어(`102. `)를 뗀 것 | 번호는 파일 대조에만 쓴다. 접두어가 없으면 원문 유지 + 경고 |
| `bike_station.dock_count` | `rackTotCnt` | 파일의 LCD+QR 합과 다르면 경고만. 비어 있으면 null |

적재하지 않는 것 (V1 에 컬럼·테이블 없음 → 스키마 변경은 별도 조율): `ARS_ID`, `정류소타입`, 노선별 `순번`(경유 순서), 대여소 `자치구`·`상세주소`·`운영방식`.

## 테스트

```bash
cd BE
./gradlew test --tests 'com.ssafy.s15p21a104.load.*'    # 단위 67 + 통합 5 (postgres 필요) = 72
```

- `BusStopParserTest`(5) · `BusRouteParserTest`(4) · `BikeStationParserTest`(6) · `MasterValidatorTest`(6): 픽스처 행으로 규칙 고정
- `UpsertWriterIT`: 마스터 3종 멱등·덮어쓰기 2건 추가 (`IT_` 접두어 격리)
- 원천 변환 스크립트: `node --test "BE/scripts/data/test/*.test.mjs"` (20건)

## 남은 일 (후속 티켓)

끝난 것 (2026-09-18 정리):

- ~~73: `bike_stock_pred` 더미는 여기서 적재한 `rental_id` 를 키로 쓴다~~ → 더미 대신 AI 산출물을 172 가 같은 `rental_id` 로 적재했다(2026-09-17, [load-bikepred.md](load-bikepred.md)). 마스터에 없는 96곳은 경고만 남기고 적재한다.
- ~~수집기(2주차): bikeList 이벤트의 `stationId` 가 그대로 `rental_id` 다~~ → 169 수집기가 그대로 쓴다([../infra/collector.md](../infra/collector.md) 2절). 버스 정류소 `stId` 는 실시간 수집을 하지 않기로 해 쓰이지 않는다([../external/api-survey.md](../external/api-survey.md) 4절 결정 6).
- ~~버스 대기시간 근거 없음~~ → 배차간격을 228 로 채웠다(위 "배차간격" 절). 그래프가 읽는 것은 A 파트 후속.

남은 것:

- 서비스 권역 확정 시 버스·따릉이 필터 파라미터(자치구 또는 bounding box) 추가.
- BUS 엣지: 정류소 간 소요시간 원천 미조사 — 지금은 `BusEdgeBuilder` 가 직선거리 ÷ 20 km/h. 도착정보 응답의 `nstnSec`·`traSpd` 가 후보인데 운행 중인 버스가 있어야 값이 와서 반복 수집이 필요하다.
- 배차간격 없는 267 노선(마을버스 243·심야 14·기타 10)의 대체 원천 — 도착정보 API 로는 불가 확정. 심야·새벽 18개는 야간 재수집(20콜 안)으로 확인할 가치가 있다.
- 대여소 마스터 갱신 — `bike_station` 은 2026-09-09 스냅샷(2,731곳)이고 예측 표는 2,824곳이다(72 후속).
- 스키마 확장 후보: `bus_stop.ars_id`(안내판 번호, FE 표시용), `bus_stop.stop_type`, `bus_route.first_bus_at`·`last_bus_at`(CSV 에는 있음 — 9일 사이 12/14 노선 변동이라 갱신 방식부터 정해야 한다).
