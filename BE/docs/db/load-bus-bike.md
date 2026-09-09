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

- 73: `bike_stock_pred` 더미는 여기서 적재한 `rental_id` 를 키로 쓴다.
- 수집기(2주차): bikeList 이벤트의 `stationId` 가 그대로 `rental_id` 다. 정류소 `stId` → `stop_id` 도 변환 없음.
- 서비스 권역 확정 시 버스·따릉이 필터 파라미터(자치구 또는 bounding box) 추가.
- BUS 엣지(`edge_time` BUS): 노선별 파일의 `순번` 을 그대로 쓴다. 정류소 간 소요시간 원천은 미조사.
- 스키마 확장 후보: `bus_stop.ars_id`(안내판 번호, FE 표시용), `bus_stop.stop_type`.
