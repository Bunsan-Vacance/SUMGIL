# 경로 API 명세 초안 (S15P21A104-63 / S15P21A104-65)

> **초안이다. FE와 맞추기 전 단계.** 확정되면 이 문서를 갱신하고 Notion에도 옮긴다 (두 티켓의 결과물이 "API 명세 (Notion)").

경로 그래프·다익스트라 구현(`S15P21A104-94~98`)이 아직 없어서, 두 엔드포인트 다 처음엔 mock으로 응답하고 준비되면 교체한다.

## 공통 사항

- 모든 응답은 `ApiResult<T>` 래퍼(`{success, timestamp, traceId, data, error}`)로 나간다 — `BE/docs/global/overview.md` 참고.
- 경로는 `/api/v1/...`가 아니라 **`/api/...`**로 간다 — `S15P21A104-63` 티켓 원문이 `GET /api/routes/search`를 명시한다. `BE/README.md` 2절의 `/api/v1/` 초안과 다른데, 이 문서가 실제 작업 지시라서 이 표기를 따른다. **`BE/README.md` 2절은 이 문서 확정 후 같이 갱신해야 한다.**
- 역 식별자는 `station.station_id`를 그대로 쓴다 (예: `0222`).

## 1. `GET /api/routes/search` (S15P21A104-63)

출발역·도착역을 받아 **경로 후보 목록**을 우선순위 순으로 반환한다. 혼합 경로(지하철 타다가 중간에 따릉이로 갈아타는 것도 그래프상 하나의 경로라 후보에 포함될 수 있다 — `EdgeTime.mode`가 애초에 `SUBWAY`/`BIKE`/`BUS`/`WALK`/`TRANSFER`를 다 표현하게 설계돼 있다).

**역전구간(2번 엔드포인트, `reversal`)과의 차이**: 이 엔드포인트는 사전계산된 평균 소요시간(`edge_time` 등, 정적) 기준으로 후보를 계산한다. `reversal`은 여기서 나온 경로 중 하나를 사용자가 실제로 타고 있다고 가정하고, **지금 이 순간의 실시간 따릉이 재고**까지 반영해 "지금 갈아타는 게 나은지"를 별도로 판단한다 — 정적 계산과 실시간 보정을 분리한 것. (이 구분이 맞는지는 알고리즘 파트 확인 필요 — 아래 "열린 질문" 참고.)

### 요청

| 파라미터 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `originStationId` | String | Y | 출발역 `station_id` |
| `destStationId` | String | Y | 도착역 `station_id` |
| `modes` | String (콤마 구분, 예: `SUBWAY,BIKE`) | N | 교통수단 필터. **복수 선택 가능.** `TravelMode` 값 중 골라서 넘긴다. 생략하면 전체 조합 다 봄 |

### 응답 (`RouteSearchResponse`) — 배열이다

```json
{
  "success": true,
  "timestamp": "2026-09-08T10:00:00+09:00",
  "traceId": "550e8400-e29b-41d4-a716-446655440000",
  "data": [
    {
      "totalMinutes": 13.2,
      "legs": [
        { "mode": "SUBWAY", "fromNodeId": "0222", "toNodeId": "0221", "routeId": "2", "minutes": 5.0 },
        { "mode": "BIKE", "fromNodeId": "0221", "toNodeId": "0220", "routeId": null, "minutes": 7.4 },
        { "mode": "WALK", "fromNodeId": "0220", "toNodeId": "0220-EXIT2", "routeId": null, "minutes": 0.8 }
      ],
      "source": "MOCK"
    },
    {
      "totalMinutes": 15.6,
      "legs": [
        { "mode": "SUBWAY", "fromNodeId": "0222", "toNodeId": "0221", "routeId": "2", "minutes": 8.2 },
        { "mode": "TRANSFER", "fromNodeId": "0221", "toNodeId": "0221", "routeId": null, "minutes": 3.0 },
        { "mode": "WALK", "fromNodeId": "0221", "toNodeId": "0221-EXIT4", "routeId": null, "minutes": 4.4 }
      ],
      "source": "MOCK"
    }
  ]
}
```

- 배열 순서 = 우선순위 순. **정렬 기준은 아직 미정** — 단순 `totalMinutes` 오름차순인지, README 3절의 "구간 점수 = 소요시간 + λ × 혼잡 페널티" 가중치 순인지는 추후 논의.
- `legs[].mode` — `TravelMode` enum(`WALK`/`BIKE`/`BUS`/`SUBWAY`/`TRANSFER`) 그대로 노출. `EdgeTime.mode`와 동일한 값이라 FE가 아이콘 매핑하기 쉽다.
- `source` — `"MOCK"` | `"ALGORITHM"`. 알고리즘 파트 연동 전까지는 `MOCK` 고정, 연동되면 `ALGORITHM`. 완료 기준의 "mock으로 대체 후 이슈에 명시"를 응답 자체에서도 드러내기 위한 필드 — **논의 필요, FE가 이 필드를 안 써도 되면 빼도 됨.**
- **미정**: 착석 기회 지수·혼잡도(`congestionRate`)를 이 엔드포인트에 넣을지, 아니면 별도 엔드포인트(README 2절의 `seat-chance`)로 뺄지는 아직 안 정함.
- **미정**: 후보가 하나도 없을 때(필터 조건에 맞는 경로가 없음)는 빈 배열(`[]`)인지 `ROUTE_NOT_FOUND` 에러인지.

### 실패

| 상황 | ErrorType (이미 정의됨) | HTTP |
| --- | --- | --- |
| 출발지 == 도착지 | `SAME_ORIGIN_DEST` | 400 |
| 역 ID가 존재하지 않음 | `STATION_NOT_FOUND` | 404 |
| 경로를 찾을 수 없음 (그래프상 연결 안 됨) | `ROUTE_NOT_FOUND` | 404 |

세 코드 다 `ErrorType`에 이미 있다 — 이 엔드포인트를 염두에 두고 먼저 정의해둔 것으로 보인다.

## 2. `GET /api/routes/reversal` (S15P21A104-65)

역전구간(지하철 대비 따릉이 대안) **판정 결과를 Redis에서 조회해 그대로 서빙**한다. 판정 자체는 계산하지 않는다 — 값이 없으면 없는 대로 응답한다.

### 요청

| 파라미터 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `originStationId` | String | Y | 현재(출발) 역 `station_id` |
| `destStationId` | String | Y | 목적지 역 `station_id` |

`dowType`·`timeSlot`은 파라미터로 받지 않고 **요청 시각 기준으로 서버가 계산**해서 `CacheKeys.reversal(...)` 키를 만든다 (`BE/docs/db/schema.md`의 "조회는 요청 시각이 아니라 구간 진입 예상 시각을 기준으로 한다" 원칙과는 별개로, 이 조회 자체는 "지금" 캐시를 보는 것이므로 요청 시각 기준이 맞다고 본다 — **이 부분 알고리즘 파트와 확인 필요**).

### 응답 — 캐시 히트(`ReversalResponse`)

`BE/README.md` 2절의 기존 `escape` 초안 구조를 그대로 가져왔다. 실제 필드는 캐시에 무엇이 채워지는지에 달려있어 **미정 — 알고리즘 파트와 맞춰야 한다.**

```json
{
  "success": true,
  "timestamp": "2026-09-08T10:00:00+09:00",
  "traceId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "subway": { "totalMinutes": 15, "congestionRate": 148 },
    "bike": { "totalMinutes": 13, "source": "OBSERVED_MEDIAN" },
    "verdict": "BIKE_FASTER",
    "blockedReason": null
  }
}
```

### 응답 — 캐시 미스

**미정 — 팀 결정 필요.** 후보:

1. `success: false` + 새 에러코드(`REVERSAL_RESULT_NOT_FOUND`, 404) — `ErrorType`에 추가해야 함.
2. `success: true` + `data: null` (판정 결과 없음은 오류가 아니라 "아직 준비 안 된 정상 상태"로 본다)

캐시 미스는 두 경우에 다 생길 수 있다 — 진짜로 사전계산 범위 밖인 구간이거나, 배치/스트림이 아직 안 채웠거나. 이 둘을 구분해서 내려줄지도 정해야 한다.

### Redis 연동

- 키: `CacheKeys.reversal(originStationId, destStationId, dowType, timeSlot)` (`global/cache/CacheKeys`, `S15P21A104-61`에서 만듦)
- TTL: 30분 (같은 클래스에 상수로 있음)
- 이 엔드포인트는 **읽기 전용**이다 — 캐시를 채우는 로직(배치 적재 또는 cache-aside)은 포함하지 않는다. `BE/docs/cache/strategy.md` "다음 Task에서 할 일" 1번 참고.

## 결정된 것 (팀 논의 반영, 2026-09-08)

- `search`는 경로 후보를 **여러 개, 배열로** 우선순위 순 반환한다 (하나만 주는 게 아님).
- `modes` 필터는 **복수 선택 가능** (예: 지하철+따릉이 조합만 보기).
- 위 두 가지 때문에, 혼합 경로(지하철+따릉이)는 `search`의 후보 중 하나로 자연스럽게 나올 수 있다 — `reversal`과 역할이 완전히 겹치진 않지만 경계가 흐려질 여지가 있음 (아래 열린 질문 1).

## 열린 질문 (알고리즘 파트·FE와 같이 확인)

1. **`search`가 만드는 혼합 경로(정적 계산)와 `reversal`(실시간 재고 반영)의 역할 구분이 이 설계로 맞는지** — 알고리즘 파트(`전우석`, 그래프/다익스트라 담당)가 실시간 재고를 그래프 계산에 아예 안 넣는다는 전제가 맞아야 지금 구분이 성립한다. 만약 넣는다면 `reversal`은 `search` 결과의 부분집합이 되어 역할이 겹친다.
2. **우선순위(정렬) 기준** — 단순 `totalMinutes` 순인지, README 3절 λ 가중 점수인지. 추후 논의하기로 함.
3. `GET /api/routes/search` 응답에 `source: MOCK|ALGORITHM` 필드를 넣을지.
4. 캐시 미스(`reversal`) 시 에러로 볼지 정상 응답(`data: null`)으로 볼지.
5. 후보가 하나도 없을 때(`search`) 빈 배열인지 에러인지.
6. `BE/README.md` 2절의 `/api/v1/` 프리픽스를 없애는 쪽으로 문서를 갱신할지 (이 문서는 없앤 쪽으로 초안 작성함).
