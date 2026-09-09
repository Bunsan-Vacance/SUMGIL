# API 명세 (S15P21A104-63 / S15P21A104-64) — FE 협의 반영본

> **`GET /api/routes/search`(63), `GET /api/bike-stations/nearby`(64) 둘 다 구현 완료.** `search`는 mock 데이터로 응답한다. `nearby`는 실제 DB 조회(하버사인 거리 계산)로 동작한다. 둘 다 로컬에서 실제 요청까지 확인함(2026-09-08).

> 이 문서가 최종 기준이다. 이전 초안(`route-api-spec.md`, `mvp-api-overview.md`, `bike-station-api-spec.md`)은 논의 과정 기록으로 남겨두고, 앞으로는 이 문서를 갱신한다. 확정되면 Notion으로 옮긴다.

FE 검토 의견(`api-spec-fe-review.md`, 2026-09-08)을 반영해 정리했다.

## 결정된 것

| 항목 | 결정 |
| --- | --- |
| API 경로 | `/api/v1/...`이 아니라 **`/api/...`**로 통일 (README 2절도 이후 갱신) |
| 경로 검색 구조 | `GET /api/routes/search` 하나로 혼합 경로까지 배열 반환 |
| 정렬 | BE가 정렬해서 내려주고 FE는 그대로 표시. 정렬 기준 자체는 미정(아래 열린 질문) |
| `legs`에 역/장소 이름 | `fromNodeName`/`toNodeName` 추가 |
| `modes` 필터 의미 | "이 수단들만 **허용**"(합집합) — "반드시 다 포함"이 아님. `WALK`/`TRANSFER`는 필터와 무관하게 항상 연결 구간으로 포함 |
| 결과 없음 | `search`·`bike-stations/nearby` 둘 다 **`200` + `data: []`** (에러 아님) |
| 잘못된 입력(역 없음, 위경도 범위 밖 등) | 위 결과 없음과 구분되는 **에러**로 응답 |
| 서비스 지역 밖 | `search`가 처리. 구분되는 에러 코드 필요 → `OUT_OF_SERVICE_AREA` 신설 (아래 실패 표) |
| 대여소 API 경로 | `GET /api/bike-stations/nearby` |
| 대여소 기본값 | `radiusMeters` 기본 500, `limit` 기본 20 / 최대 100 |
| `dockCount` | 거치대 **총 개수**만 표시. 실시간 대여 가능 대수 아님 |
| `source` 필드 | 유지 (mock/실제 구분 용도) |
| 안내 종료·중단(F-02-10/11) | 서버 기록 요구사항 없으면 API 불필요, FE 처리 |
| `priority`(쾌적/시간 우선) | 일단 지금 초안(`TIME`\|`COMFORT`) 그대로 둔다. 경로 추천 로직이 구체화되면 그때 같이 조정 |
| 지도 표시용 좌표 | **MVP는 지점 좌표만 제공.** `legs`에 `fromLat`/`fromLng`/`toLat`/`toLng` 추가 (아래 예시 참고). 지점 사이 실제 이동 경로선(폴리라인)은 범위 밖 — 필요해지면 별도 Task |
| 카카오 검색 ↔ 내부 ID 연결 | FE는 건물/장소를 카카오 API로 직접 불러온다. 우리 쪽 역·정류소·대여소 데이터를 만드는 건 별도 BE 작업이고, 필요하면 다른 BE 팀원이 그때 손본다 — 지금 이 명세를 막는 요소 아님 |

## 남은 논의사항

| # | 내용 | 누구와 |
| --- | --- | --- |
| 1 | `routeType` 최종 목록 — 지금 실제로 만들 수 있는 건 `SHORTEST`, `SHORTEST_WITH_BIKE` 정도로 보임 (혼잡회피는 데이터(`S15P21A104-73`) 준비 전). 버스 포함 여부도 확인 필요 | 알고리즘(전우석)·FE |
| 2 | 정렬 기준 — 단순 시간순인지 추천 점수(README 3절 λ 가중치)인지 | 알고리즘·기획 |
| 3 | 혼합 경로 추천 시 **실제 대여·반납 가능 여부 보장** — 지금 설계(cache-aside, `S15P21A104-61`)가 실시간 재고를 반영하는지, 아니면 거치대 존재만 보고 추천하는지 알고리즘 쪽과 확정 필요 | 알고리즘 |
| 4 | 대여소 검색 **반경 최대값**(안: 3000m) 및 잘못된 반경·개수 값 처리(범위 밖이면 400인지 클램핑인지) | FE |

---

## 1. `GET /api/routes/search`

### 배경 — "역전구간"

"지하철 최단경로보다 중간에 다른 수단(따릉이 등)으로 갈아타는 게 더 빠른 구간." 별도 API 없이 이 엔드포인트의 혼합 경로 후보로 흡수한다. 계산은 BE 경로 알고리즘(전우석, `ROUTE-002`)이 하고, 같은 구간·시간대 반복 요청에 대비해 Redis에 cache-aside로 캐시한다(`S15P21A104-61`).

### 요청

| 파라미터 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `originStationId` | String | Y | 출발역 `station_id` |
| `destStationId` | String | Y | 도착역 `station_id` |
| `modes` | String (콤마 구분) | N | 허용 수단 집합. 생략 시 전체 허용. `WALK`/`TRANSFER`는 항상 허용(연결 구간이라 필터 대상 아님) |
| `priority` | String (`TIME` \| `COMFORT`) | N | 정렬/계산 우선순위. 일단 이 값으로 두고 추천 로직 구체화되면 조정 |

### 응답 — 배열

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
        {
          "mode": "SUBWAY",
          "fromNodeId": "0222", "fromNodeName": "한티", "fromLat": 37.5049, "fromLng": 127.0530,
          "toNodeId": "0221", "toNodeName": "역삼", "toLat": 37.5006, "toLng": 127.0364,
          "routeId": "2", "minutes": 5.0,
          "geometry": {
            "type": "MultiLineString",
            "coordinates": [[[127.0530, 37.5049], [127.0480, 37.5030]], [[127.0480, 37.5030], [127.0364, 37.5006]]]
          },
          "geometryStatus": "available"
        },
        {
          "mode": "BIKE",
          "fromNodeId": "0221", "fromNodeName": "역삼", "fromLat": 37.5006, "fromLng": 127.0364,
          "toNodeId": "ST-1577", "toNodeName": "역삼역 3번출구 대여소", "toLat": 37.4998, "toLng": 127.0371,
          "routeId": null, "minutes": 7.4
        }
      ],
      "source": "MOCK"
    }
  ]
}
```

| 필드 | 설명 |
| --- | --- |
| `routeType` | 경로 유형. 초기 제공값: `SHORTEST`, `SHORTEST_WITH_BIKE` (열린 질문 1) |
| `legs[].mode` | `TravelMode`(`WALK`/`BIKE`/`BUS`/`SUBWAY`/`TRANSFER`) |
| `legs[].fromNodeName`/`toNodeName` | 신규 추가 (FE 요청) |
| `legs[].fromLat`/`fromLng`/`toLat`/`toLng` | 신규 추가. 구간 시작·끝 지점 좌표(`station`/`bus_stop`/`bike_station` 테이블 값) — 지도에 마커 찍는 용도 |
| `legs[].routeId` | 지하철/버스 노선 ID. 도보·환승·따릉이 구간은 `null` |
| `legs[].geometry` | **[미승인, FE 제안]** SUBWAY 구간 실선로 좌표. GeoJSON `MultiLineString` — KTDB link 여러 개를 이어붙인 것이며 하나의 연속선으로 합치지 않고 link 단위 좌표 배열을 그대로 담는다. 매칭 안 되면 `null` |
| `legs[].geometryStatus` | **[미승인, FE 제안]** `"available"` \| `"unavailable"`. SUBWAY 이외 구간(WALK/BIKE/BUS/TRANSFER)은 항상 `"unavailable"`(KTDB는 철도망 데이터라 대상 아님) |
| `source` | `"MOCK"` \| `"ALGORITHM"` |

- 결과 0개면 `data: []` (에러 아님).
- **지점 좌표까지만 제공한다.** 두 지점 사이 실제 이동 경로선(도로를 따라가는 폴리라인)은 이 응답에 없음 — MVP 범위 밖. (단, SUBWAY 구간의 KTDB `geometry`는 예외 — FE 요청으로 위 필드에서 별도 제공, S15P21A104-63 확장)

### 실패

| 상황 | ErrorType | HTTP |
| --- | --- | --- |
| 출발지 == 도착지 | `SAME_ORIGIN_DEST` (기존) | 400 |
| 역 ID가 존재하지 않음 | `STATION_NOT_FOUND` (기존) | 404 |
| 서비스 지역 밖 | `OUT_OF_SERVICE_AREA` (**신규 추가 필요**) | 400 |

(그래프상 연결 안 됨 등 "경로 없음"은 에러가 아니라 `data: []`로 통일했다 — 위 "결정된 것" 참고. 기존 `ROUTE_NOT_FOUND`는 그래프 자체가 끊긴 명백한 예외 상황에만 쓸지, 아예 안 쓸지 확인 필요.)

---

## 2. `GET /api/bike-stations/nearby`

좌표 기준 근처 따릉이 대여소 조회. **실시간 재고 미포함** — 위치·거치대 수만 준다.

### 요청

| 파라미터 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `lat` | Double | Y | 기준 위도 |
| `lng` | Double | Y | 기준 경도 |
| `radiusMeters` | Integer | N | 기본 500. 최대값 확인 필요(안 3000) — 열린 질문 6 |
| `limit` | Integer | N | 기본 20, 최대 100 |

### 응답 — 배열

```json
{
  "success": true,
  "data": [
    {
      "rentalId": "ST-1577",
      "name": "역삼역 3번출구 대여소",
      "lat": 37.5006,
      "lng": 127.0364,
      "dockCount": 12,
      "distanceMeters": 150.0
    }
  ]
}
```

- 거리순 오름차순 정렬.
- 결과 0개면 `data: []`.
- `dockCount`는 거치대 총 개수. 실시간 대여 가능 대수(재고)는 이 API에 없음 — 데이터 파이프라인 연동 후 별도 Task(`S15P21A104-61`의 `bike:stock` 캐시 사용 예정).

### 실패

| 상황 | ErrorType | HTTP |
| --- | --- | --- |
| `lat`/`lng` 범위 밖 | `BAD_REQUEST` | 400 |
| `radiusMeters`/`limit`이 허용 범위 밖 | `BAD_REQUEST` (범위: 열린 질문 6) | 400 |
