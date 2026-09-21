# 탑승 정보 조회 API 사용 가이드 (S15P21A104-300/313)

설계 배경·범위는 [boarding-check-api-design.md](./boarding-check-api-design.md) 참고. 이 문서는
**이 API를 실제로 호출/조회하려는 사람**(FE 연동 담당, AI 배치 담당)을 위한 실전 가이드다.

## FE 연동 담당에게

**아직 FE와 연동돼 있지 않다.** `FE/src/features/guidance/GuidanceDialogs.tsx`의 "탑승 확인" 다이얼로그
(`dialog === 'train'`)는 지금 `onTrain(time: string)`을 호출해 로컬 상태(`useGuidance`)만 바꾸고, 어디로도
전송하지 않는다(`FE/docs/setup.md` 5절: "실제 API 모드에서는 ... 탑승 확인을 사용할 수 없고"). 이 API는
그 `onTrain` 콜백 안에서 호출하면 되는 자리다.

### 언제 호출하나

사용자가 다이얼로그에서 시간을 고르거나("09:38" 등) "잘 모르겠어요"를 눌렀을 때, 그 leg 정보와 함께
1번 호출한다. 응답은 무시해도 되고(fire-and-forget), 실패해도 안내 흐름을 막지 않는다 — 탑승 확인은
안내 진행에 필수가 아니라 참고 데이터 수집이다.

### 요청 매핑

`GuidanceDialogs`가 갖고 있는 `leg: Leg`(경로 응답의 `RouteLegResponse`)에서 그대로 채우면 된다.

| 요청 필드 | FE 쪽 값 |
| --- | --- |
| mode | `leg.mode` (WALK/BIKE/BUS/SUBWAY/TRANSFER) |
| fromNodeId / fromNodeName | `leg.fromNodeId` / `leg.fromNodeName` |
| toNodeId / toNodeName | `leg.toNodeId` / `leg.toNodeName` |
| routeId / routeName | `leg.routeId` / `leg.routeName` |
| status | 시간을 골랐으면 `"BOARDED"`, "잘 모르겠어요"면 `"UNKNOWN"` |
| departureTime | 고른 시간 문자열(`"09:38"`). UNKNOWN이면 생략 가능 |
| reportedAt | 호출 시점의 현재 시각 (ISO 8601, 예: `new Date().toISOString()`) |

### 호출 예시

```bash
curl -X POST http://localhost:8080/api/boardings \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "SUBWAY",
    "fromNodeId": "222",
    "fromNodeName": "역삼역",
    "toNodeId": "223",
    "toNodeName": "선릉역",
    "routeId": "1002",
    "routeName": "2호선",
    "status": "BOARDED",
    "departureTime": "09:38",
    "reportedAt": "2026-09-21T09:38:00+09:00"
  }'
```

응답(성공):

```json
{
  "success": true,
  "data": {
    "id": 1,
    "mode": "SUBWAY",
    "fromNodeId": "222",
    "fromNodeName": "역삼역",
    "toNodeId": "223",
    "toNodeName": "선릉역",
    "routeId": "1002",
    "routeName": "2호선",
    "status": "BOARDED",
    "departureTime": "09:38",
    "reportedAt": "2026-09-21T09:38:00+09:00"
  }
}
```

필수 필드(mode/fromNodeId/toNodeId/status/reportedAt) 중 하나라도 비면 `400 BAD_REQUEST`.

## AI·다른 BE 도메인 담당에게

**조회용 API는 없다.** `congestion_pred`·`bike_stock_pred`와 같은 방식으로, `boarding_event` 테이블을
직접 읽으면 된다.

```sql
SELECT mode, from_node_id, to_node_id, route_id, status, departure_time, reported_at
FROM boarding_event
WHERE reported_at >= now() - interval '1 day'
ORDER BY reported_at DESC;
```

`from_node_id`/`to_node_id` 조합에 인덱스(`idx_boarding_event_from_to`)가 있어 특정 구간 필터링은 빠르다.
사용자 식별자는 없다 — 세션·개인화가 필요해지면 이 API부터 다시 설계해야 한다(로그인 도입 전제).

## 아직 안 된 것 (연동 담당이 알아야 할 것)

- FE `onTrain` 콜백에서 이 API를 실제로 호출하는 작업 — FE 파트 별도 작업.
- "탑승 안 함"(NOT_BOARDED) 케이스 — 지금 FE 다이얼로그엔 그 버튼이 없어서 status enum에도 아직 없다.
  필요해지면 `BoardingStatus`에 값 추가 + 마이그레이션 없이 바로 확장 가능(문자열 컬럼이라).
