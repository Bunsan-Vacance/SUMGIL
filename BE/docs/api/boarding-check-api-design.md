# 탑승 정보 조회 API 설계 (S15P21A104-300)

## 배경

사용자가 경로 안내 중 특정 구간(지하철/버스 등)에 실제로 탑승했는지(또는 어느 열차/버스에 탑승했는지)를
체크하면, 그 정보를 BE의 다른 파트나 AI 파트에서 재사용할 수 있게 저장해두는 API.

FE에는 이미 "탑승 확인" 다이얼로그(`GuidanceDialogs.tsx`의 `dialog === 'train'`)가 있지만, 이건
**샘플 모드 전용 로컬 상태**다 — `FE/docs/setup.md` 5절: "실제 API 모드에서는 경로 제안과 탑승 확인을
사용할 수 없고". 즉 FE는 UI/상호작용은 만들어뒀지만 백엔드로 아무것도 보내지 않는 상태였고, 이 API가
그 연결점이다. AI·다른 BE 도메인 쪽에도 탑승 이벤트를 다루는 코드가 없어(그렙 결과 전무) 새 도메인으로 만든다.

## 범위

- 이 프로젝트는 로그인이 없는 공개 API다(`BE/docs/infra/splunk-siem-design.md`에서도 같은 전제). 그래서
  "누가" 탑승했는지는 식별하지 않고, "어떤 구간에 탑승 이벤트가 있었다"만 기록한다 — 개인화·세션 연결은
  범위 밖.
- 조회 API는 만들지 않는다. AI/다른 BE 도메인은 기존 `congestion_pred`·`bike_stock_pred`처럼 테이블을
  직접 읽으면 된다(배치 산출물 소비 패턴과 동일).

## API

```
POST /api/boardings
```

### Request

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| mode | TravelMode(WALK/BIKE/BUS/SUBWAY/TRANSFER) | Y | 탑승 구간의 이동 수단 |
| fromNodeId | string | Y | 승차 지점 ID (역/정류장) |
| fromNodeName | string | N | 승차 지점 이름 |
| toNodeId | string | Y | 하차 지점 ID |
| toNodeName | string | N | 하차 지점 이름 |
| routeId | string | N | 노선 ID (지하철 lineId·버스 노선 ID 등) |
| routeName | string | N | 노선 이름 |
| status | BoardingStatus(BOARDED/UNKNOWN) | Y | 탑승 확인 결과. FE "잘 모르겠어요" → UNKNOWN |
| departureTime | string("HH:mm") | N | 사용자가 고른 열차/버스 출발 시각. status=UNKNOWN이면 null |
| reportedAt | OffsetDateTime | Y | 클라이언트에서 이 이벤트가 발생한 시각 |

### Response

```json
{
  "success": true,
  "data": {
    "id": 1,
    "mode": "SUBWAY",
    "fromNodeId": "222",
    "toNodeId": "223",
    "routeId": "1002",
    "status": "BOARDED",
    "departureTime": "09:38",
    "reportedAt": "2026-09-21T09:38:00+09:00"
  }
}
```

### 오류

| 상황 | ErrorType |
| --- | --- |
| mode/fromNodeId/toNodeId/status/reportedAt 누락 | BAD_REQUEST |

## 저장

새 테이블 `boarding_event` (V8 마이그레이션). PK는 자동 증가 `id` — 링크 PK(from/to/line)로 묶지 않는
이유는 같은 구간에 여러 번(하루에 여러 번 같은 역 지나는 등) 이벤트가 쌓일 수 있어서다.

## 이후 구현(S15P21A104-313)에서 다루지 않는 것

- 조회/집계 API, 대시보드 — 필요해지면 별도 티켓.
- 세션·사용자 식별 — 로그인 도입 전에는 범위 밖.
- FE 연동(다이얼로그가 실제로 이 API를 호출하도록 바꾸는 작업) — FE 파트 작업.
