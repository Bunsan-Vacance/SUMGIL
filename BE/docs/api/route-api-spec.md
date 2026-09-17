# 경로 검색 API 명세 (S15P21A104-63)

> **FE 리뷰용 초안.** 논의 확정되면 이 문서를 갱신하고 Notion에도 옮긴다 (`S15P21A104-63`의 결과물이 "API 명세 (Notion)").

경로 그래프·다익스트라 구현(`S15P21A104-94~98`)이 아직 없어서, 처음엔 mock으로 응답하고 준비되면 교체한다.

## 배경 — "역전구간"이 뭔가요

기획서·README에 나오는 **"역전구간"**은 "지하철로만 가는 최단경로보다, 중간에 다른 수단(주로 따릉이)으로 갈아타는 게 더 빨라지는 구간"을 뜻한다.

처음엔 이걸 별도 API(`GET /api/routes/reversal`)로 만들려고 했는데, 논의 끝에 **별도 엔드포인트를 만들지 않기로 했다.** 이유: "역전구간 판정"은 사실 혼합 경로(지하철+따릉이 등)를 찾는 경로 알고리즘 자체가 하는 일이라, `search` 하나의 응답 안에 "혼합 경로 후보" 형태로 자연스럽게 들어갈 수 있기 때문이다. FE 입장에서 바뀌는 건 없다 — **API는 `search` 하나뿐이다.**

내부적으로는 이렇게 동작한다 (FE가 알 필요는 없지만 참고용):

```
search 요청 (같은 구간·시간대)
      │
      ▼
Redis에 이 구간·시간대의 "혼합 경로가 더 빠른지" 계산 결과 캐시 있나?
      │
   있음 ──▶ 캐시값 바로 사용 (재계산 안 함)
      │
   없음 ──▶ 경로 알고리즘(전우석 담당, ROUTE-002)이 계산
                │
                ▼
         결과를 Redis에 30분 TTL로 저장 후 사용
```

같은 시간대(30분)에 같은 구간을 검색하는 사용자가 많을 걸 감안해, 매번 다시 계산하지 않고 캐시해서 재사용하는 것뿐이다 (`S15P21A104-61`에서 만든 `CacheKeys`/`RedisConfig` 사용). **AI/데이터 파트가 아니라 BE 내부 경로 알고리즘이 계산한다.**

## 공통 사항

- 모든 응답은 `ApiResult<T>` 래퍼(`{success, timestamp, traceId, data, error}`)로 나간다 — `BE/docs/global/overview.md` 참고.
- 경로는 `/api/v1/...`가 아니라 **`/api/...`**로 간다 — `S15P21A104-63` 티켓 원문이 `GET /api/routes/search`를 명시한다. `BE/README.md` 2절의 `/api/v1/` 초안과 다른데, 이 문서가 실제 작업 지시라서 이 표기를 따른다. **`BE/README.md` 2절은 이 문서 확정 후 같이 갱신해야 한다.**
- 역 식별자는 `station.station_id`를 그대로 쓴다 (예: `0222`).

## `GET /api/routes/search`

출발역·도착역을 받아 **경로 후보 목록**을 우선순위 순으로 반환한다. 최단(지하철만)·최단(따릉이 추가)·혼잡회피 등 여러 유형이 한 응답 안에 섞여 나온다.

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
      "routeType": "SHORTEST_WITH_BIKE",
      "totalMinutes": 13.2,
      "legs": [
        { "mode": "SUBWAY", "fromNodeId": "0222", "toNodeId": "0221", "routeId": "2", "minutes": 5.0 },
        { "mode": "BIKE", "fromNodeId": "0221", "toNodeId": "0220", "routeId": null, "minutes": 7.4 },
        { "mode": "WALK", "fromNodeId": "0220", "toNodeId": "0220-EXIT2", "routeId": null, "minutes": 0.8 }
      ],
      "source": "MOCK"
    },
    {
      "routeType": "SHORTEST",
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

| 필드 | 설명 |
| --- | --- |
| `routeType` | 경로 유형 태그. 후보값(안): `SHORTEST`, `SHORTEST_WITH_BIKE`, `SHORTEST_WITH_BUS`, `CONGESTION_AVOID`, `CONGESTION_AVOID_WITH_BIKE`. **정확한 값 목록은 열린 질문 1 참고.** |
| `totalMinutes` | 총 소요시간(분) |
| `legs[].mode` | `TravelMode` enum(`WALK`/`BIKE`/`BUS`/`SUBWAY`/`TRANSFER`). `EdgeTime.mode`와 동일한 값이라 FE가 아이콘 매핑하기 쉽다 |
| `legs[].routeId` | 지하철/버스 노선 ID. 도보·환승·따릉이 구간은 `null` |
| `source` | `"MOCK"` \| `"ALGORITHM"`. 알고리즘 연동 전까지는 `MOCK` 고정. **논의 필요 — 열린 질문 2** |

- 배열 순서 = 우선순위 순. **정렬 기준은 미정** — 단순 `totalMinutes` 오름차순인지, README 3절의 "구간 점수 = 소요시간 + λ × 혼잡 페널티" 가중치 순인지는 추후 논의 (열린 질문 3).
- 이 응답은 **경로 선택 후 턴바이턴(스텝) 안내 화면에도 그대로 쓰인다** — `legs` 배열이 곧 스텝 리스트다. 위치 없이 사용자가 다음/이전으로 넘기거나 시간 경과로 자동 진행하는 건 FE 쪽 로직이고, 서버에 추가로 물어볼 건 없다. 역 이름 표시가 필요하면 `legs`에 `fromNodeName`/`toNodeName` 추가가 필요할 수 있음 (열린 질문 4).

### 실패

| 상황 | ErrorType (이미 정의됨) | HTTP |
| --- | --- | --- |
| 출발지 == 도착지 | `SAME_ORIGIN_DEST` | 400 |
| 역 ID가 존재하지 않음 | `STATION_NOT_FOUND` | 404 |
| 경로를 찾을 수 없음 (그래프상 연결 안 됨 / 필터 조건에 맞는 경로 없음) | `ROUTE_NOT_FOUND` | 404 |

세 코드 다 `ErrorType`에 이미 정의돼 있다. 필터 결과가 0개일 때 에러로 볼지 빈 배열로 볼지는 열린 질문 5.

## 결정된 것 (팀 논의 반영, 2026-09-08)

- API는 **`search` 하나**다. "역전구간 판정"을 위한 별도 엔드포인트는 만들지 않는다 — 혼합 경로 후보로 흡수.
- 응답은 **여러 경로 후보의 배열**이며, 각 후보에 `routeType`을 붙여 유형을 구분한다.
- `modes` 필터는 **복수 선택 가능**.
- "역전구간" 계산은 경로 알고리즘(전우석, `ROUTE-002`)이 하고, BE는 그 결과를 Redis에 cache-aside로 캐시한다 (`S15P21A104-61`의 `CacheKeys`/`RedisConfig` 재사용). AI/데이터 파트 배치가 아니다.

## 열린 질문 (알고리즘 파트·FE와 같이 확인)

1. `routeType` 값 목록을 위 5개(안)로 확정할지 — 혼잡회피가 아직 알고리즘/데이터(`S15P21A104-73`) 준비 전이라 초기엔 `SHORTEST`/`SHORTEST_WITH_BIKE`만 나올 수도 있음.
2. `source: MOCK|ALGORITHM` 필드를 응답에 넣을지, FE가 안 쓰면 뺄지.
3. 정렬 기준 — 단순 시간순인지 λ 가중 점수인지.
4. `legs`에 역 이름(`fromNodeName`/`toNodeName`)을 넣을지, FE가 station 목록을 별도로 들고 있다가 ID로 매핑할지.
5. 후보가 0개일 때 빈 배열(`[]`)인지 `ROUTE_NOT_FOUND` 에러인지.
6. `BE/README.md` 2절의 `/api/v1/` 프리픽스를 없애는 쪽으로 문서를 갱신할지 (이 문서는 없앤 쪽으로 초안 작성함).
