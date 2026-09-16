# 혼잡도 정적 적재 (S15P21A104-73)

> `congestion` 을 서울교통공사 지하철혼잡도정보에서 채우는 로더. 코드는 `com.ssafy.s15p21a104.load.crowd`,
> 원천과 설정은 `src/main/resources/data/crowd/` (출처·열·읽는 규칙은 그 폴더 README).
> NFR-D01(산출 4종을 채운다) 충족용이며 **혼잡도를 읽는 코드는 아직 없다** — 소비는 A 파트의 `RouteType.CONGESTION_AVOID` 몫이다.

## 실행

```bash
cd BE
SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun --args='--load.sources=congestion --load.dry-run=true'   # 파싱·검증·건수만
SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun --args='--load.sources=congestion'                        # 실제 적재
```

**지하철 적재가 선행 조건이다.** 검증이 `target_id` 를 적재된 `station`·`line` 과 대조하므로, 역이 없으면 오류로 멈춘다.
`application-load.yml` 의 기본 `sources` 는 `subway,bus,bike,railgeometry,congestion` 순서다.

## 2026-09-10 적재 결과 (로컬 postgres:16)

| 항목 | 값 |
| --- | --- |
| 원천 | 1,671행 (`서울교통공사_지하철혼잡도정보_20260630`, 1~8호선) |
| 매핑된 역 | **240** (282 (역번호,호선) 쌍 → 276 codes 매핑 + 별칭 6) · 모르는 역번호 **0행** |
| 슬롯 | **39/48** (11~47 + 0~1). 01:00~05:29 는 행 없음 |
| `congestion` | **29,016행** = `STATION` 28,080 (240역 × 3요일 × 39슬롯) + `LINE` 936 (8노선 × 3 × 39) |
| 적재 시간 | 0.6초 (약 45,000 행/초). 두 번째 실행도 29,016행 — 멱등 |
| `level` 범위 | `STATION` 0.0 ~ **144.6** · `LINE` 0.0 ~ 92.4 |
| 100 초과 | 원천 셀 **340** → DB `STATION` 행 **331** (같은 물리 역·요일·슬롯에서 방향·노선이 겹쳐 최대 하나로 합쳐진 9건 차이) |

요일별 평균이 상식과 맞는다: 평일 42.3 · 토요일 36.2 · 일요일 25.5 (각 9,672행).

| 노선 | 평균 | 최대 |
| --- | --- | --- |
| 1001 | 31.4 | 84.2 |
| 1002 | 39.9 | 89.8 |
| 1003 | 30.4 | 77.7 |
| 1004 | 36.7 | 79.9 |
| 1005 | 31.3 | 72.9 |
| 1006 | 26.5 | 60.1 |
| 1007 | 38.3 | 91.9 |
| 1008 | 35.4 | 90.5 |

## 값 규칙

- **`STATION` = 그 물리 역의 모든 노선·방향 중 최대값.** `station_id` 가 노선 코드 최솟값이라 환승역은 노선별 원천 행이 한 ID 로 합쳐진다(1~8호선에 35개). 경로 추천에서 혼잡을 보수적으로 봐야 하므로 최대를 쓴다.
- **`LINE` = 그 노선 안에서만 낸 평균.** (노선, 역) 단위 방향 최대를 노선별로 평균한다. 서울역 평일 08:30 을 보면 `STATION 150` = 92.2(전체 최대)인데 `LINE 1001` = 66.4 · `LINE 1004` = 70.8 로 노선별 값이 보존된다.
- `source = 'stat'` (통계). 실시간 값이 생기면 같은 키를 `live` 가 덮는다.
- **`level` 은 100 을 넘을 수 있다** — 정원 대비 %다. 읽는 쪽이 0~100 을 가정하면 안 된다.
- 원천이 덮지 않는 슬롯·빈 칸·모르는 역번호는 **행을 만들지 않는다**.

## 데이터 흐름

```
seoulmetro-congestion.csv ─▶ CongestionParser ─▶ CongestionRow(STATION 28,080 + LINE 936) ─┐
data/subway/conf/station-ids(codes 역방향) ─┐                                              ├─▶ MasterValidator.validateCongestion ─▶ UpsertWriter.upsertCongestion
conf/crowd-station-aliases(가상 역번호 6) ──┴─▶ CrowdStationCodes ─────────────────────────┘        (적재된 station·line 과 대조, 오류면 중단)
```

## 읽는 쪽에 미치는 영향

- `congestion` 이 처음 채워졌다. `RouteType` 주석의 *"혼잡회피 등은 관련 데이터(S15P21A104-73) 준비 후 추가한다"* 전제가 이제 성립한다 — `CONGESTION_AVOID`·`RoutePriority.COMFORT` 구현이 가능해졌다.
- **1~8호선 240역만 있다.** 9호선·코레일 구간·113 으로 넣은 9개 노선 등 324역은 행이 없다. 조회가 빈 결과를 주므로 소비 쪽에 "혼잡도 없음" 처리가 필요하다.
- **01:00~05:29 슬롯이 없다.** 요청 시각이 그 구간이면 행이 없다.
- 스키마 변경 없음. V1 의 `level` 주석만 "100 초과 가능"으로 고쳤다.

## 테스트

```bash
cd BE
./gradlew test --tests 'com.ssafy.s15p21a104.load.crowd.*'      # 파서 11 + 역번호 매핑 5
./gradlew test --tests '*MasterValidatorTest'                    # 혼잡도 검증 4 포함 10
./gradlew test --tests '*UpsertWriterIT'                         # congestion 멱등·덮어쓰기 (postgres 필요)
```

- `CongestionParserTest`(11): 시각 열 → 슬롯, 요일 매핑, 방향 최대, **환승역 노선별 LINE**, 100 초과 유지, 모르는 역번호 집계 경고, 빈 칸, line_id 없는 호선, 통계, 모르는 구분
- `CrowdStationCodesTest`(5): codes 역방향, 앞 0 무관, 별칭 우선, 모르는 번호, 잘못된 별칭 중단
- 증적: `.claude/tdd/73-congestion-load.tdd.md`

## 남은 일 (후속 티켓)

- **`bike_stock_pred` 적재 (S15P21A104-115)** — 73 에서 분리했다. 더미를 넣으면 `BikeStockGate` 가 가짜 값으로 따릉이 경로를 걸러내므로 AI 78 산출물을 기다린다.
- 1~8호선 밖 324역의 혼잡도 추정 — AI CROWD 트랙(승하차 데이터 기반).
- 방향별 혼잡도가 필요해지면 `congestion` 스키마 변경(타깃에 방향 추가) 검토.
- 실시간 혼잡도(`source='live'`) — 수집기 티켓. 서울시 실시간 API 는 도착정보만 주므로 SK open API 칸별 혼잡도 등 별도 원천 필요(`AI/README.md` 참고).
