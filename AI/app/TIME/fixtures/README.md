# TIME reroute/check 응답 fixture (S15P21A104-323-3)

FE 통합용 `POST /time/reroute/check` 4상태 실응답. 손으로 쓴 예시가 아니라 `test/TIME/test_time_fixtures.py`가 가짜 BE 어댑터·가짜 LLM·로컬 색인으로 실제 엔드포인트를 호출해 만든 값이다. 각 파일은 `{"request": ..., "response": ...}` 모양.

| 파일 | 상태 | 조건 |
| --- | --- | --- |
| `reroute_check_no_trigger.json` | `no_trigger` | 임계 미달(`below_threshold`) |
| `reroute_check_no_alternative.json` | `no_alternative` | 대체 대여소 없음(`no_nearby_station`) |
| `reroute_check_unavailable.json` | `unavailable` | 대상 대여소를 못 찾음(`target_unknown`) |
| `reroute_check_proposal.json` | `proposal` | (가짜) LLM이 대안을 골라 경로까지 이어짐 |

`recommendationId`(`uuid4`)는 고정값(`00000000-0000-0000-0000-000000000000`)으로, `validUntil`은 테스트 고정 시각(2026-09-23 09:00 KST) 기준으로 저장돼 있다 — 실제 응답과는 다르다.

`reroute_check_proposal.json`의 `route.legs[0]`은 첫 leg 검증(324, `service._pick_route_from_alternative`)을 통과하도록 `fromNodeId`가 선택된 대안(`alternative.rentalId`)과 같다 — BE가 이 값을 보장하지 않으므로(`FROM_BE-bike-reroute-route-02.md` 1번) 가짜 BE 응답에서 직접 맞춰준 값이다.

## 재생성

```bash
cd AI && PYTHONIOENCODING=utf-8 TIME_FIXTURES_UPDATE=1 conda run -n SUMGIL --no-capture-output python -m pytest -q test/TIME/test_time_fixtures.py
```

응답이 바뀌면 `TIME_FIXTURES_UPDATE` 없이 돌렸을 때 먼저 깨진다 — diff 리뷰 후에만 다시 쓴다.

## dev에서 `proposal` 재현(curl)

`TIME_DEBUG_FORCE_TRIGGER_ENABLED=true`인 dev 서버에서 `debugForceTrigger`로 임계값을 건너뛰어 강제로 띄운다(조회 실패 자체는 못 건너뛴다):

```bash
curl -X POST http://localhost:8000/time/reroute/check -H "Content-Type: application/json" -d '{"sessionId":"dev-1","step":0,"rentalId":"<대여소 ID>","etaToRentalMinutes":10,"destStationId":"<목적지 ID>","boundary":{"legIndex":1,"nodeId":"<하차역 nodeId>","lat":37.5665,"lng":126.978},"debugForceTrigger":true}'
```
