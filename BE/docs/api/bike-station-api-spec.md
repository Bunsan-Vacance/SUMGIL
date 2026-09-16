# 따릉이 대여소 조회 API 명세 (S15P21A104-64)

> **FE 리뷰용 초안.** 논의 확정되면 이 문서를 갱신하고 Notion에도 옮긴다.

좌표 기준으로 근처 따릉이 대여소를 조회한다. **실시간 재고는 포함하지 않는다** — 대여소 위치·거치대 수 같은 정적 정보만 준다. 실시간 재고(`bike:stock:{rentalId}`, `S15P21A104-61`에서 만든 Redis 캐시)를 합쳐서 보여주는 건 데이터 파이프라인 연동 후 별도 Task.

## 공통 사항

- 응답은 `ApiResult<T>` 래퍼 — `route-api-spec.md`·`BE/docs/global/overview.md`와 동일.
- 대여소 식별자는 `bike_station.rental_id`를 그대로 쓴다 (예: `ST-1577`).

## ⚠️ 경로 이름에 대한 열린 질문

티켓 원문은 `GET /api/stations/nearby`인데, **`station`은 이 프로젝트 스키마에서 지하철 역 전용 용어다** (`BE/docs/db/schema.md`: "`station_id`는 역 ID 전용이다. 대여소는 `rental_id`, 정류소는 `stop_id`를 사용한다"). `/api/stations/nearby`라고 하면 "지하철역 검색"으로 오해할 수 있다.

`BE/README.md` 2절 원래 초안은 `GET /api/v1/bike-stations/nearby`였다 — 이 이름이 더 명확해 보인다. **경로를 `bike-stations`로 바꿀지, 티켓 원문 그대로 `stations`로 갈지 확인 필요** (아래 표는 일단 `bike-stations`로 작성함).

## `GET /api/bike-stations/nearby`

### 요청

| 파라미터 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `lat` | Double | Y | 기준 위도 |
| `lng` | Double | Y | 기준 경도 |
| `radiusMeters` | Integer | N | 검색 반경(m). 기본값 미정 — 열린 질문 참고 |
| `limit` | Integer | N | 최대 개수. 기본값 미정 |

### 응답 (`BikeStationResponse`) — 배열

```json
{
  "success": true,
  "timestamp": "2026-09-08T10:00:00+09:00",
  "traceId": "550e8400-e29b-41d4-a716-446655440000",
  "data": [
    {
      "rentalId": "ST-1577",
      "name": "논현역 10번출구",
      "lat": 37.5111,
      "lng": 127.0222,
      "dockCount": 12,
      "distanceMeters": 150.0
    }
  ]
}
```

- `rentalId`/`name`/`lat`/`lng`/`dockCount` — `BikeStation` 엔티티 필드 그대로 (`domain/bike/entity/BikeStation`).
- `distanceMeters` — 요청 좌표(`lat`/`lng`)로부터의 거리. DB 컬럼이 아니라 조회 시 계산.
- 배열은 **거리순 오름차순** 정렬.
- **재고 필드(`available` 등)는 없다** — 위 "공통 사항" 참고.

### 실패

| 상황 | ErrorType | HTTP |
| --- | --- | --- |
| `lat`/`lng`가 유효 범위 밖(위경도 아님) | `BAD_REQUEST` (기존 코드 재사용) | 400 |
| 반경 안에 대여소가 하나도 없음 | **미정** — 빈 배열 vs 에러, `search`(63)와 같은 결정을 따르는 게 일관적일 듯 | - |

## 결정된 것

(아직 없음 — 이번이 첫 초안)

## 열린 질문 (FE와 같이 확인)

1. **경로명**: `/api/bike-stations/nearby` vs 티켓 원문 `/api/stations/nearby`.
2. **`radiusMeters` 기본값** — 얼마로 할지 (예: 500m?).
3. **`limit` 기본값/최대값** — 지도에 마커로 몇 개까지 뿌릴지에 따라 다름, FE 화면 설계에 달림.
4. 반경 안에 대여소가 0개일 때 빈 배열인지 에러인지 — `route-api-spec.md` 열린 질문 5(경로 후보 0개)와 같은 기준으로 가는 게 일관적일 것 같음.
5. 지금은 대여소 마스터 데이터가 임시값일 수 있다(`S15P21A104-64` "막히는 점": 데이터 파이프라인 적재 전이면 임시 데이터로 진행) — FE 테스트 시 데이터가 적을 수 있음을 미리 안내.
