# Mock 엔드포인트 (백엔드 초기 세팅)

`S15P21A104-60` 백엔드 초기 세팅 작업으로 만든 두 엔드포인트. 알고리즘/데이터 파트 로직이 아직 없어 컨트롤러가 mock 데이터를 그대로 내려준다.

## GET /api/routes/search

| 항목 | 내용 |
| --- | --- |
| 컨트롤러 | `RouteController` |
| 요청 파라미터 | `origin` (String), `destination` (String) — 쿼리 파라미터 |
| 응답 | `RouteSearchResponse` |

응답 필드:

```json
{
  "origin": "...",
  "destination": "...",
  "baselineTotalMin": 13.6,
  "modeSummary": [{ "emoji": "🚇", "label": "지하철", "min": 3.6 }],
  "adjustments": [{ "label": "출발역 실시간 대기", "min": 1.0 }],
  "reversals": [{
    "station": "논현역", "baselineMin": 13.6, "bikeMin": 11.6,
    "savedMin": 2.0, "option": "논현역 10번출구 -> 신논현역 4번출구"
  }],
  "checkedOthers": [{ "station": "언주역3번출구", "note": "...", "bikeMin": 17.2 }]
}
```

## GET /api/stations/nearby

| 항목 | 내용 |
| --- | --- |
| 컨트롤러 | `StationController` |
| 요청 파라미터 | `lat` (Double), `lng` (Double) — 쿼리 파라미터 |
| 응답 | `StationResponse` 리스트 |

```json
[{ "name": "논현역 10번출구", "lat": 0.0, "lng": 0.0, "rackTotal": 12, "distanceMeters": 150.0 }]
```

## 교체 시점

- `RouteController` → 알고리즘 파트의 판정 로직(또는 이를 감싼 서비스)이 준비되면 그걸 호출하도록 교체.
- `StationController` → 데이터 수집 파트가 DB에 대여소 마스터 테이블을 채우면 그 테이블을 조회하도록 교체.

## ⚠️ `BE/README.md` API 초안과의 불일치

`BE/README.md` 2절에는 이미 다른 형태의 API 초안이 있다 — `POST /api/v1/escape`(A안/B안 비교), `POST /api/v1/routes`, `GET /api/v1/stations`처럼 `/api/v1/` 버전 프리픽스를 쓰고, 응답도 `subway`/`bike`/`verdict` 구조다.

지금 만든 `GET /api/routes/search`, `GET /api/stations/nearby`는 초기 세팅 지시문에 있던 별도 mock 명세를 그대로 반영한 것이라 **경로·메서드·응답 형태가 README의 초안과 다르다.** FE 연동 전에 둘 중 하나로 정리하고 `BE/README.md` 2절 또는 이 문서를 갱신해야 한다.
