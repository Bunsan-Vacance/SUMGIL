# 지하철 정적 적재 (S15P21A104-69)

> `line` · `station` · `transfer_meta` · `edge_time`(SUBWAY) 을 공공데이터 파일에서 채우는 로더.
> 코드는 `com.ssafy.s15p21a104.load`, 원천과 설정은 `src/main/resources/data/subway/` (출처는 그 폴더의 README).

## 실행

```bash
# 1) DB 기동 (저장소 루트)
docker compose -f Infra/docker/docker-compose.yml up -d postgres

# 2) 적재 (BE 폴더). local 프로파일이 없으면 DB_URL·DB_USERNAME·DB_PASSWORD 환경변수로 대신한다
cd BE
SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun --args='--load.dry-run=true'   # 파싱·검증·건수만
SPRING_PROFILES_ACTIVE=local,load ./gradlew bootRun                                 # 실제 적재 (BATCH)
```

| 옵션 | 기본 | 뜻 |
| --- | --- | --- |
| `--load.dry-run` | false | DB 에 쓰지 않고 그래프 건수·검증 결과만 출력 |
| `--load.write-mode` | BATCH | `edge_time` 쓰기 방식. ROW 는 성능 비교용 baseline |
| `--load.region` | (전부) | 포함할 line_id. 예 `--load.region=1002,1005`. 서비스 권역 확정 시 사용 |
| `--load.avg-speed-mps` | 9.2 | 소요시간 없는 구간의 추정 표정속도 |

- 프로파일은 **`local,load` 두 개**를 함께 준다. `logback-spring.xml` 이 `local`·`default`·`prod` 에만 콘솔 출력을 붙여 두어 `load` 만 주면 로그가 나오지 않는다.
- 몇 번 실행해도 결과가 같다 (자연키 `ON CONFLICT DO UPDATE`, `updated_at` 은 실행 시각).
- 검증 오류가 하나라도 있으면 아무것도 쓰지 않고 종료 코드 1 로 끝난다. 경고는 로그로만 남긴다.

## 2026-09-08 적재 결과 (로컬 postgres:16)

| 테이블 | 행 | 비고 |
| --- | --- | --- |
| `line` | 17 | 1~8호선 + 코레일 서비스 노선(1063, 1075) + 환승 상대 노선(1009, 1065, 1067, 1077, 1092, 1093, 1094) |
| `station` | 340 | 좌표 있음 239 (1~8호선), 없음 101 (코레일 역, 원천 없음) |
| `transfer_meta` | 199 | 1~8호선 환승역 74개, 양방향, `source=extract` |
| `edge_time` | 107,136 | 엣지 744 × 144. `timetable` 78,048 (1~8호선) + `avg` 29,088 (코레일 구간) |

검증 경고 (오류 아님):
- 노선 1001 이 10개 조각, 1004 가 3개, 1075 가 3개로 끊겨 있음 — 코레일 구간 파일이 100행짜리 부분 데이터라서다. 서울교통공사 1~8호선 구간은 모두 이어진다.
- 환승 상대 노선 "김포골드라인" 은 서울시 실시간 API 에 코드가 없어 건너뜀 (김포공항 1건).

## 데이터 흐름

```
seoulmetro-station-time (운행 순서·소요시간) ─┐
korail-segments (거리)                        ├─▶ Segment ─┐
conf/branch-anchors, korail-line-overrides ──┘            │
seoulmetro-transfer ─────────────▶ TransferRecord ────────┼─▶ SubwayGraphBuilder ─▶ LoadValidator ─▶ UpsertWriter
seoulmetro-station-coords, kric-line9 ─▶ StationCoord ────┘        (station_id 결정)      (오류면 중단)
conf/station-aliases ─▶ StationNameNormalizer (모든 역명에 적용)
```

## 식별자·값 규칙

- `station.station_id` = 정규화 역명 (괄호 부기 제거 → 별칭 표). 물리 역 1행. 노선별 승강장은 `edge_time.route_id` 로 표현.
- `line.line_id` = 실시간 지하철 API `subwayId`. 수집기가 변환 없이 route_id 로 쓴다.
- `edge_time`: 구간마다 양방향 2행 × (요일 3 × 슬롯 48). 시간대별 원천이 없어 같은 값을 복제하고, `source` 로 등급을 표시한다. `timetable` 은 서울교통공사 시간표 실측, `avg` 는 거리 ÷ 9.2 m/s (1.1 km ≈ 2분 보정) 추정, 최소 30초.
- `transfer_meta.walk_sec` 는 서울교통공사 환승거리 ÷ 1.2 m/s 값 그대로. `stair_count`·`has_elevator` 는 원천 없어 null.
- 원천에 없는 값(코레일 역 좌표, 9호선 구간, 1~8호선 밖 환승)은 **채워 넣지 않는다.** 검증기가 경고로 드러낸다.

## 스키마 변경

- **V2 `widen_source_columns`**: V1 이 `source` 를 VARCHAR(8) 로 두고 값을 `timetable|avg|model` 로 정의했지만 `timetable` 은 9자다. 통합 테스트에서 발견해 `edge_time`·`congestion`·`bike_stock_pred`·`transfer_meta` 의 `source` 를 16자로 늘렸다. 엔티티 `@Column(length)` 도 함께 16 이다.

## 테스트

```bash
cd BE
./gradlew test --tests 'com.ssafy.s15p21a104.load.*'    # 단위 46 + 통합 3 (postgres 필요)
```

단위 테스트는 픽스처 행으로 파서·빌더·검증기 규칙을 고정한다. `UpsertWriterIT` 는 실제 DB 에 두 번 써서 멱등성과 덮어쓰기를 확인한다 (`IT_` 접두어로 격리).

## 남은 일 (후속 티켓)

- 70: 시간대별 소요시간·대기시간 (`wait_sec`) 이 있는 원천이 생기면 슬롯별로 덮어쓰기. 현재 1~8호선 `travel_sec` 은 이미 `timetable` 로 들어가 있다.
- 코레일 역 좌표: 열린데이터광장 역사마스터 API(`subwayStationMaster`, 8088) 로 채우기. 실습실 망에서는 불가.
- 9호선 구간: 운행 순서 원천 확보 후 추가.
- 실시간 `statnId` ↔ `station_id` 매핑 표 (수집기 티켓).
