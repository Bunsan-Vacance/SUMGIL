# 따릉이 대여소 조회 API 명세 (S15P21A104-64, 156)

좌표 기준으로 근처 따릉이 대여소를 조회하고(`nearby`), 특정 대여소의 실시간 재고를 단건으로 조회한다(`stock`, BIKE-001 156 — FE 요청 `backend-bike-live-stock-request-20260917.md` 반영).

## 공통 사항

- 응답은 `ApiResult<T>` 래퍼 — `route-api-spec.md`·`BE/docs/global/overview.md`와 동일.
- 대여소 식별자는 `bike_station.rental_id`를 그대로 쓴다 (예: `ST-1577`). `nearby` 응답에서 받은 값을 그대로 `stock`에 넘기면 된다 — 별도 매칭 불필요.
- 실시간 재고는 수집기가 서울시 `bikeList`를 폴링(120초 주기)해 Redis(`bike:stock:{rentalId}`)에 적재한 값을 읽는다. **API가 호출마다 서울시 API를 다시 부르지 않는다.**

## `GET /api/bike-stations/nearby`

### 요청

| 파라미터 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `lat` | Double | Y | 기준 위도 |
| `lng` | Double | Y | 기준 경도 |
| `radiusMeters` | Integer | N | 검색 반경(m). 기본 500, 최대 3000 |
| `limit` | Integer | N | 최대 개수. 기본 20, 최대 100 |

### 응답 (`BikeStationResponse`) — 배열

```json
{
  "success": true,
  "timestamp": "2026-09-17T10:00:00+09:00",
  "traceId": "550e8400-e29b-41d4-a716-446655440000",
  "data": [
    {
      "rentalId": "ST-1577",
      "name": "논현역 10번출구",
      "lat": 37.5111,
      "lng": 127.0222,
      "dockCount": 12,
      "distanceMeters": 150.0,
      "availableBikes": 7,
      "stockUpdatedAt": "2026-09-17T09:58:30+09:00"
    }
  ]
}
```

- `rentalId`/`name`/`lat`/`lng`/`dockCount` — `BikeStation` 엔티티 필드 그대로.
- `distanceMeters` — 요청 좌표로부터의 거리. 배열은 거리순 오름차순 정렬.
- `availableBikes`/`stockUpdatedAt` — **캐시가 있을 때만 채워진다. 캐시가 없거나 만료됐으면 둘 다 `null`이다(에러 아님).** 신선(AVAILABLE)한 값인지 오래된(STALE) 값인지는 이 목록에서 구분하지 않는다 — 구분이 필요하면 단건 조회를 쓴다. `dockCount`(거치대 총수)와 `availableBikes`(현재 대여 가능 자전거 수)는 다른 값이다.

### 실패

| 상황 | ErrorType | HTTP |
| --- | --- | --- |
| `lat`/`lng`가 유효 범위 밖 | `BAD_REQUEST` | 400 |
| `radiusMeters`/`limit`가 허용 범위 밖(0 이하, 최대 초과) | `BAD_REQUEST` | 400 |
| 반경 안에 대여소가 없음 | 에러 아님 — 빈 배열 | 200 |

## `GET /api/bike-stations/{rentalId}/stock`

지도 아이콘 클릭 시 바텀시트에 표시할 단건 실시간 재고 조회.

### 응답 (`BikeStockResponse`)

```json
{
  "success": true,
  "timestamp": "2026-09-17T10:00:00+09:00",
  "traceId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "rentalId": "ST-1577",
    "availableBikes": 7,
    "stockUpdatedAt": "2026-09-17T09:58:30+09:00",
    "status": "AVAILABLE"
  }
}
```

| 필드 | 타입 | 의미 |
| --- | --- | --- |
| `rentalId` | string | 요청 ID와 일치 |
| `availableBikes` | integer \| null | 대여 가능 자전거 수. `status`가 `UNAVAILABLE`이면 `null` |
| `stockUpdatedAt` | ISO 8601(+09:00) \| null | 재고 관측(수집) 시각. 서버가 응답을 만든 시각이 아니다 — 조회만 반복해도 값이 바뀌지 않는다 |
| `status` | `AVAILABLE` \| `STALE` \| `UNAVAILABLE` | 아래 표 참고 |

### 신선도 판정 기준

수집 주기는 120초, Redis TTL은 300초다.

| 상황 | status | availableBikes/stockUpdatedAt |
| --- | --- | --- |
| 수집 후 180초 이내 | `AVAILABLE` | 최신 값. 자전거가 0대여도 `AVAILABLE`이다 — "값이 유효함"의 의미이지 "1대 이상 있음"이 아니다 |
| 180초는 넘었지만 캐시(TTL 300초)는 살아있음 | `STALE` | 마지막 값·시각을 그대로 반환. 현재 재고로 단정하지 않는다 |
| 캐시 없음(한 번도 수집 안 됨, 또는 TTL 만료) | `UNAVAILABLE` | 둘 다 `null` |

180초 = 수집 주기(120초)의 1.5배다. 한 회차를 놓쳐도 바로 STALE로 떨어뜨리지 않되, TTL(300초)보다는 짧게 잡아 STALE 구간이 존재하도록 했다.

### 실패

| 상황 | ErrorType | HTTP |
| --- | --- | --- |
| 등록되지 않은 `rentalId` | `BIKE_STATION_NOT_FOUND` | 404 |
| Redis 조회 자체가 실패(장애) | `INTERNAL_SERVER_ERROR` | 500 |

### FE 연동 시 참고

- 아이콘 클릭 → 바텀시트 로딩 → 이 API 호출 → 재고 표시. 지도 표시 토글(아이콘 on/off)은 FE 로컬 상태이며 이 API와 무관.
- 연속 클릭 시 응답 역전(늦게 도착한 이전 요청이 최신 요청 결과를 덮어쓰는 것) 방지는 FE 쪽 책임 — API는 매 호출이 독립적인 스냅샷이다.
- 로컬 검증 시 실제 수집기가 안 떠 있으면 캐시가 비어 있어 전부 `UNAVAILABLE`로 보인다 — 정상이다. 수집기·환경별 기동 방법은 `BE/docs/infra/kafka.md`, `BE/README.md` 9절 참고.

## 수집 파이프라인 변경 (BE 내부, FE 영향 없음)

기존에는 수집 → Kafka 전송만 하고, Redis 캐시는 별도 `consume` 프로세스가 Kafka를 구독해야 채워졌다. 이제 수집기가 Kafka 전송과 **동시에** 같은 반영 로직으로 Redis에도 바로 적재한다(`CompositeEventPublisher`) — `consume` 프로세스가 안 떠 있어도 이 API가 최신 캐시를 읽을 수 있다. Redis 적재가 실패해도 Kafka 전송(AI 파이프라인 원천)은 막지 않는다.

## 결정된 것

- 경로: `/api/bike-stations/nearby`, `/api/bike-stations/{rentalId}/stock` (지하철 역과 구분하기 위해 `stations`가 아닌 `bike-stations` 사용).
- `radiusMeters` 기본 500m·최대 3000m, `limit` 기본 20·최대 100.
- 반경 안 대여소 0개는 에러가 아니라 빈 배열.
- 재고 없음/오래됨/정상은 값을 지어내지 않고 `null`·`STALE`·`AVAILABLE`로 구분해서 내려준다.
