# 운영자 뷰 읽기 API (`/api/ops/**`)

운영자 뷰(FE `#/ops`)가 mock 없이 실데이터로 그리도록 만든 **읽기 전용** API 2건이다. 최종 사용자 화면에서는 쓰지 않는다 — 사용자 화면은 기존 `/api/bike-stations`·`/api/congestion`·`/api/routes`를 쓴다. 인증은 현재 BE 전체와 같은 조건(없음)이며, 운영자 뷰의 공개 노출은 Infra·BE 접근 정책 뒤에서 결정한다.

- 코드: `com.ssafy.s15p21a104.domain.ops` (controller / dto / service / repository)
- 응답 래퍼: 기존과 같은 `ApiResult<T>` (`success`, `timestamp`, `traceId`, `data`, `error`)
- 읽기만 한다: PostgreSQL 조회 + Redis GET. 쓰기·Kafka·수집기 빈·마이그레이션 없음.

## 1. `GET /api/ops/bike-stations/stock-overview`

지도 bbox 안 따릉이 대여소의 실시간 재고와 도착 시각 예측을 한 번에 돌려준다.

### 요청 파라미터

| 이름 | 필수 | 설명 |
| --- | --- | --- |
| `swLat`, `swLng` | O | bbox 남서 모서리 (위도 -90~90, 경도 -180~180) |
| `neLat`, `neLng` | O | bbox 북동 모서리. `swLat < neLat`, `swLng < neLng` 이어야 한다 |
| `arrivalTime` | X | 예측 기준 시각(offset ISO, 예 `2026-10-03T12:00:00+09:00`). 생략하면 서버 현재 시각 |
| `limit` | X | 최대 반환 수. 기본 200, 범위 1~500 |

### 응답 `data`

| 필드 | 설명 |
| --- | --- |
| `arrivalTime` | 예측 기준 시각(같은 instant) |
| `count` | `items` 개수 |
| `truncated` | `limit` 때문에 잘렸으면 `true`. 잘릴 때는 **bbox 중심에서 가까운 순**으로 남긴다 |
| `generatedAt` | 응답 생성 시각 |
| `items[]` | 대여소 목록(중심 거리순) |

`items[]` 필드:

| 필드 | 설명 |
| --- | --- |
| `rentalId`, `name`, `lat`, `lng` | 대여소 식별·위치 |
| `rackCount` | 총 거치대 수(실시간 값이 없으면 `null`) |
| `availableBikes` | 현재 대여 가능 자전거 수(없으면 `null`) |
| `stockStatus` | `AVAILABLE`(신선도 창 180초 이내) / `STALE`(캐시는 있으나 창을 넘김, 마지막 값 그대로) / `UNAVAILABLE`(캐시 없음, 값 전부 `null`) |
| `stockUpdatedAt` | 재고 수집 시각(없으면 `null`) |
| `predictedBikes` | 도착 시각 예상 재고(`exp_bikes`를 HALF_UP 반올림) |
| `availabilityProbability` | 대여 가능 확률 = `1 - p_empty`, 0~1로 제한 |
| `predictionStatus` | `AVAILABLE` / `UNAVAILABLE` |
| `predictionSource` | 항상 `TABLE` |
| `predictedAt` | 예측표 행의 산출 시각(`updated_at`) |

### 의미 규칙

- **`null`은 "알 수 없음"이다. 0으로 해석하면 안 된다.** `stockStatus=UNAVAILABLE`이면 `availableBikes`·`rackCount`·`stockUpdatedAt`이 `null`이고, `predictionStatus=UNAVAILABLE`이면 `predictedBikes`·`availabilityProbability`·`predictedAt`이 `null`이다.
- **일괄 예측은 `bike_stock_pred` 표만 읽는다(`TABLE`).** AI 모델은 부르지 않는다. 단건 `GET /api/bike-stations/{rentalId}/prediction`은 도착 30분 이내면 모델(`MODEL`)을 먼저 쓰므로 같은 대여소라도 값이 다를 수 있다. 200건 안팎을 모델로 돌리는 것은 운영자 뷰 목적에 과해서 나눴다.
- `arrivalTime`은 Asia/Seoul로 바꿔 `(dow_type, time_slot)`을 만든다(`DepartureSlot` 규칙: 0 평일 / 1 토 / 2 일·공휴일, 30분 단위 0~47). 슬롯은 응답 전체에서 한 번만 계산하고 예측표는 한 번의 쿼리로 읽는다.
- 부족/여유 색 판정(예: ≤2 부족, ≥5 여유)은 FE 표시 규칙이다. 서버는 판정하지 않는다.
- 서버 캐시는 없다(Redis가 이미 캐시). FE 폴링은 60초를 가정한다.

## 2. `GET /api/ops/congestion/heatmap`

`congestion_pred`(링크×방향×슬롯 예측)를 호선×슬롯 셀로 집계해 히트맵용으로 돌려준다.

### 요청 파라미터

| 이름 | 필수 | 설명 |
| --- | --- | --- |
| `date` | X | `YYYY-MM-DD`. 생략하면 Asia/Seoul 오늘 |

### 응답 `data`

| 필드 | 설명 |
| --- | --- |
| `date` | 조회 날짜 |
| `source` | 항상 `"congestion_pred"`. 기존 `GET /api/congestion`(정적 `congestion` 표)과 다른 표임을 드러낸다 |
| `generatedAt` | 해당 날짜 행의 `generated_at` 최댓값(행이 없으면 `null`) |
| `predictorVersions[]` | 해당 날짜에 쓰인 `predictor_version` 목록(없으면 빈 배열) |
| `slotFrom`, `slotTo` | 10, 47 |
| `lines[]` | `{ lineId, lineName, cells[] }` — 호선은 `line_id` 순 |

`cells[]`(호선마다 슬롯 10~47, 38칸, 슬롯 오름차순):

| 필드 | 설명 |
| --- | --- |
| `timeSlot` | 슬롯 번호(30분 단위, 10 = 05:00, 47 = 23:30~24:00) |
| `level` | 혼잡도 % 중앙값(소수 1자리). 행이 없으면 `null` |
| `nLinks` | 집계에 쓰인 링크×방향 행 수(행이 없으면 0) |
| `nFallback` | 그중 `calibration_fallback` 행 수 |
| `maxLevel` | 최댓값(행이 없으면 `null`) |

### 집계 규칙과 근거

- 대상 행: `data_status IN ('ok', 'calibration_fallback')` 이고 `level IS NOT NULL`. `segment_truncated`(구간 절단)는 값 신뢰도가 달라 **제외**한다. `calibration_fallback`은 **포함**하되 `nFallback`으로 비중을 알려 FE가 표시할 수 있게 한다.
- 대표값은 **중앙값**(`percentile_cont(0.5)`)이다. 평균은 종점·저밀도 링크에 끌려 호선 전체의 인상을 왜곡해서 쓰지 않았다. `maxLevel`은 병목 확인용으로 같이 준다.
- 방향은 합친다(방향별 분리는 후속).
- 슬롯 축은 **10~47 고정**(05:00~24:00, 38칸). 원천은 0~47을 가지지만 운영 시간 밖 슬롯은 표시하지 않는다. 행이 없는 슬롯은 `level=null`, `nLinks=0` 셀로 채워 FE가 축을 따로 만들 필요가 없다 — 값을 지어내지 않는다.
- **데이터가 없는 날짜는 200에 `lines: []`**(`generatedAt=null`, `predictorVersions=[]`)이다. 에러가 아니다.
- 집계 쿼리는 `pred_date`(PK 선두)로 좁혀 하루 약 2만 행을 훑는다. 인덱스는 추가하지 않았다.

## 3. 오류 코드

| 상황 | 응답 |
| --- | --- |
| bbox가 뒤집힘(`sw >= ne`), 좌표 범위 밖, 필수 좌표 누락·형식 오류 | 400 `BAD_REQUEST` |
| `limit`이 1~500 밖 | 400 `BAD_REQUEST` |
| `arrivalTime`이 offset ISO가 아님 | 400 `BAD_REQUEST` |
| `date`가 `YYYY-MM-DD`가 아님 | 400 `BAD_REQUEST` |

데이터 부재(재고 캐시 없음, 예측 행 없음, 해당 날짜 혼잡도 없음)는 오류가 아니라 위의 상태·`null`·빈 배열로 표현한다.
