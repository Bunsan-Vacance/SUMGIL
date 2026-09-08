# 스키마·엔티티 설계 (V1)

> 초기 구축 시점의 설계다. 변경될 수 있다.

마이그레이션은 `src/main/resources/db/migration/V1__init.sql`에 있다.
**V2 `widen_source_columns`**: `source` 열(edge_time·congestion·bike_stock_pred·transfer_meta)을 VARCHAR(16)으로 확대 — V1의 VARCHAR(8)에는 값 규약의 `timetable`(9자)이 들어가지 않았다 (S15P21A104-69).
테이블 9종 (마스터 5종, 산출 4종)이며 파일 내 순서는 의존성 순이다.

## 용어

| 명사 | 대상 | 테이블 |
|---|---|---|
| 역 | 지하철역 | `station` |
| 정류소 | 버스정류소 | `bus_stop` |
| 대여소 | 따릉이 대여소 | `bike_station` |
| 노선 | 지하철 노선 | `line` |
| 버스노선 | 버스 노선 | `bus_route` |

`station_id`는 역 ID 전용이다. 대여소는 `rental_id`, 정류소는 `stop_id`를 사용한다.
`노선` 단독 사용 시 지하철 노선을 가리킨다. 버스 노선은 반드시 `버스노선`으로 표기한다.

## 수단

| 코드 | 한글 표기 |
|---|---|
| SUBWAY | 지하철 |
| BUS | 버스 |
| BIKE | 따릉이 |
| WALK | 도보 |

코드의 영문이 정본이며 한글은 표시용이다.

## 마스터

| 테이블 | 키 | 내용 |
|---|---|---|
| `station` | `station_id` | 역 ID·이름·좌표 |
| `bus_stop` | `stop_id` | 정류소 ID·이름·좌표 |
| `bike_station` | `rental_id` | 대여소 ID·이름·좌표·거치대 수 |
| `line` | `line_id` | 노선 ID·이름 (경로 legs 표시용) |
| `bus_route` | `route_id` | 버스노선 ID·번호 (경로 legs 표시용) |

역과 정류소는 컬럼 구성이 같으나 분리한다. 역은 노선에 소속되고 환승이 발생하며,
정류소는 노선을 경유하므로 연결 관계가 다르다.

## 산출

| 테이블 | 키 | 내용 |
|---|---|---|
| `edge_time` | `from·to·mode·route·dow·slot` | 탐색 그래프의 엣지 |
| `congestion` | `target·dow·slot` | 혼잡도 0.0~100.0 |
| `bike_stock_pred` | `rental·dow·slot` | 도착 예상 시각 기준 재고 예측 |
| `transfer_meta` | `station·from·to` | 동일 역 내 노선 간 환승 정보 |

## 복합 기본키

위 테이블을 외래키로 참조하는 테이블이 없으며 모두 독립 조회용이므로
자연키를 복합 기본키로 사용한다. 대리키를 추가하면 인덱스만 증가한다.
자연키가 변경되는 경우에는 기본키를 재검토한다.

## 모드-노드 규칙

스키마로 강제하지 않으며 적재 시 검증한다.

- SUBWAY는 역과 역을, BUS는 정류소와 정류소를, BIKE는 대여소와 대여소를 연결한다.
  동일 정점 쌍도 노선마다 다른 행이 된다.
- `route_id`는 노선 한정자이다. SUBWAY·TRANSFER는 `line_id`,
  BUS는 `bus_route.route_id`, WALK는 `'-'`를 쓴다.
- WALK는 모든 정점 간 이동이 가능하며 수단 간 연결을 전담한다.
- TRANSFER는 동일 역 내 노선 간 이동에 사용한다.
- `dow_type`은 0 평일 / 1 토요일 / 2 일요일·공휴일이다.
  `time_slot`은 30분 단위 슬롯 (0~47)이다.
  조회는 요청 시각이 아니라 구간 진입 예상 시각을 기준으로 한다.
- `source`는 값의 등급을 나타낸다 (`timetable|avg|model`, `stat|live`).
  데이터가 개선되면 이 값만 변경된다.

## 타임스탬프 구분

| 경우 | 예시 | 처리 |
|---|---|---|
| `updated_at` 필요 | `edge_time`·`congestion` (주기적 갱신, 신선도 표기) | 일반 컬럼이며 적재 프로세스가 기록한다 |
| 변경 빈도 낮음 | `line`·`bus_route` | 컬럼은 유지하고 미사용 시 비워둔다 |
| `created_at`만 필요 | 적재 실행 이력(`job_run`), 에러 로그 | `BaseCreatedTimeEntity`를 상속한다 |
| 양쪽 필요 | 애플리케이션이 작성·수정하는 테이블 (향후) | `BaseTimeEntity`를 상속한다 |

적재 테이블에 감사(auditing)를 적용하지 않는 이유는
JPA가 아닌 적재 프로세스가 값을 기록하기 때문이다.
상속은 애플리케이션 작성 테이블이 추가될 때 사용한다.

## 엔티티 매핑

- `domain/{station,route,congestion,bike,bus}/entity` 패키지에 둔다.
  복합키는 `@EmbeddedId`로 매핑한다.
- `mode`·`target_type`은 enum의 STRING 매핑을 사용한다.
  정수형은 Integer, TIMESTAMPTZ는 OffsetDateTime으로 매핑한다.
- 조회 전용이므로 감사 설정과 setter를 두지 않는다.
  적재용 생성 수단이 필요해지면 추가한다.
