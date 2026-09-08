# 경로 API 명세 초안 (S15P21A104-63 / S15P21A104-65)

> **초안이다. FE와 맞추기 전 단계.** 확정되면 이 문서를 갱신하고 Notion에도 옮긴다 (두 티켓의 결과물이 "API 명세 (Notion)").

경로 그래프·다익스트라 구현(`S15P21A104-94~98`)이 아직 없어서, 두 엔드포인트 다 처음엔 mock으로 응답하고 준비되면 교체한다.

## 공통 사항

- 모든 응답은 `ApiResult<T>` 래퍼(`{success, timestamp, traceId, data, error}`)로 나간다 — `BE/docs/global/overview.md` 참고.
- 경로는 `/api/v1/...`가 아니라 **`/api/...`**로 간다 — `S15P21A104-63` 티켓 원문이 `GET /api/routes/search`를 명시한다. `BE/README.md` 2절의 `/api/v1/` 초안과 다른데, 이 문서가 실제 작업 지시라서 이 표기를 따른다. **`BE/README.md` 2절은 이 문서 확정 후 같이 갱신해야 한다.**
- 역 식별자는 `station.station_id`를 그대로 쓴다 (예: `0222`).

## 1. `GET /api/routes/search` (S15P21A104-63)

출발역·도착역을 받아 경로 탐색 결과를 반환한다. **역전구간(지하철 vs 따릉이) 비교는 포함하지 않는다** — 그건 2번 엔드포인트다.

### 요청

| 파라미터 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `originStationId` | String | Y | 출발역 `station_id` |
| `destStationId` | String | Y | 도착역 `station_id` |

### 응답 (`RouteSearchResponse`)

```json
{
  "success": true,
  "timestamp": "2026-09-08T10:00:00+09:00",
  "traceId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "originStationId": "0222",
    "destStationId": "0221",
    "totalMinutes": 15.6,
    "legs": [
      { "mode": "SUBWAY", "fromNodeId": "0222", "toNodeId": "0221", "routeId": "2", "minutes": 8.2 },
      { "mode": "TRANSFER", "fromNodeId": "0221", "toNodeId": "0221", "routeId": null, "minutes": 3.0 },
      { "mode": "WALK", "fromNodeId": "0221", "toNodeId": "0221-EXIT4", "routeId": null, "minutes": 4.4 }
    ],
    "source": "MOCK"
  }
}
```

- `legs[].mode` — `TravelMode` enum(`WALK`/`BIKE`/`BUS`/`SUBWAY`/`TRANSFER`) 그대로 노출. `EdgeTime.mode`와 동일한 값이라 FE가 아이콘 매핑하기 쉽다.
- `source` — `"MOCK"` | `"ALGORITHM"`. 알고리즘 파트 연동 전까지는 `MOCK` 고정, 연동되면 `ALGORITHM`. 완료 기준의 "mock으로 대체 후 이슈에 명시"를 응답 자체에서도 드러내기 위한 필드 — **논의 필요, FE가 이 필드를 안 써도 되면 빼도 됨.**
- **미정**: 착석 기회 지수·혼잡도(`congestionRate`)를 이 엔드포인트에 넣을지, 아니면 별도 엔드포인트(README 2절의 `seat-chance`)로 뺄지는 아직 안 정함.

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

## 열린 질문 (FE 리뷰 시 같이 확인)

1. 경로 두 개(`/api/routes/search`, `/api/routes/reversal`)로 나눈 게 맞나, 아니면 README 초안처럼 `POST /api/v1/escape` 하나로 합쳐서 지하철/따릉이 비교까지 한 번에 내려주는 게 나은가?
2. `GET /api/routes/search` 응답에 `source: MOCK|ALGORITHM` 필드를 넣을지.
3. 캐시 미스 시 에러로 볼지 정상 응답(`data: null`)으로 볼지.
4. `BE/README.md` 2절의 `/api/v1/` 프리픽스를 없애는 쪽으로 문서를 갱신할지 (이 문서는 없앤 쪽으로 초안 작성함).
