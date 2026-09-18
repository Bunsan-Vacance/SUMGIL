# FE 인수인계 — 경로 탐색 수정분 (원인 · 해결방안 · 결과)

> 작성일: 2026-09-18 · 기준 BE: `origin/develop-BE` (213·214·190·194·192·193 머지済)
> 읽는 법: 항목별 원인 → 해결방안 → 결과(API 변경사항)만 적는다. 내부 구현 서술 없음.
> Jira: S15P21A104-231~237 (BE) — FE 티켓은 FE에서 발행.

## 1. 좌표 출발 시 역 직결 누락 (231)

- 원인: 출발점 반경 500m 접근 후보를 역·정류장·대여소 통합 상위 5곳으로 잘라 정류장 밀집지에서 역이 탈락. `PLACE-ORIGIN → 역` 엣지 미생성.
- 해결방안: 유형별 보장 슬롯 (최근접 역 최소 1곳 + 정류장 + 대여소 각 N곳).
- 결과(API 변경사항): 응답 필드·순서 변경 없음. 같은 요청에 역 직결 WALK leg가 추가될 수 있고, `modes=[SUBWAY]` 빈 배열이 해소된다.

## 2. 환승 횟수 0회 (232)

- 원인: WALK를 거치면 이전 대중교통 노선 비교가 끊겨 실제 환승이 누락. 덕소→광화문 첫 후보 3회가 `transferCount=0`.
- 해결방안: WALK 경유 시 직전 대중교통 노선 유지 → 다음 대중교통과 비교. 비용·leg·횟수·순위에 동일 기준.
- 결과(API 변경사항): `transferCount` 값이 바로잡힌다 (0 → 실제 횟수). 필드 추가·삭제 없음. `TRANSFER` leg 구성이 바뀔 수 있다.

## 3. 출구 왕복 도보 (233)

- 원인: 역내 환승이어야 할 구간이 출구 경유 왕복 WALK로 탐색됨 (예: 종로3가→2번출구 뒤→종로3가). 왕복이 환승 비용 없이 계산되어 정상 환승보다 짧게 잡힘.
- 해결방안: 출구 왕복 제거 + `transfer_meta.outdoor=false` 역내 환승 적용.
- 결과(API 변경사항): 왕복 WALK legs 소멸, `TRANSFER` leg 소요가 실측값으로 변경 (예: 종로3가 1→5호선 260초). `totalMinutes`가 함께 정정된다.

## 4. 버스 동일 경로 중복 해소 (234 구현済)

- 원인: 노선ID만 다른 동일 물리 경로가 K 슬롯 독식.
- 해결: 탐색은 정류장 쌍당 1개 정규 엣지(`routeId: "BUS"`), 노선 목록은 leg에 인라인.
- 결과(API 변경사항): BUS leg에 `routeOptions: [{routeId, routeName|null, headwayMin|null}]` 추가.
  `routeId`는 `"BUS"` 고정, `routeName`은 null. 비BUS leg는 `routeOptions: null`.
  lazy 상세 endpoint 신설 없음 (데이터가 무거워지면 졸업).

## 5. 탐색 지연 3.2초 (235)

- 원인: Yen spur마다 그래프 전체 재조립 + 다익스트라 재실행.
- 해결방안: 재조립 없이 금지 집합 전달 방식. 응답 동등 유지.
- 결과(API 변경사항): 없음 (지연만 개선, p95 500ms 미만 목표).

## 6. `congestionPrediction` 추가 (236)

- 원인: 기존 `comfort.*` 폐기, FE 표시용 예측 필드 미제공.
- 해결방안: 후보별 4필드 제공 (서버 등급 판정 50/100).
- 결과(API 변경사항): `RouteSearchResponse`에 `congestionPrediction` 추가.
  `{ congestionPercent: number | null, congestionGrade: LOW|MEDIUM|HIGH | null, dataStatus: AVAILABLE|LINE1_TRUNCATED|NO_CALIBRATION|NO_LOOKUP (필수), predictionBasis: RECENT_7D|PARTIAL|WEEKDAY_AVERAGE | null }`.
  AVAILABLE 외 상태에서는 3개 값 전부 null. null = 예측 정보 없음 (0%/LOW로 해석 금지).

## 7. leg 확장 + bike prediction (237)

- 원인: 구간 의미·대여소 식별 불가, 도착 예측 endpoint 404.
- 해결방안: leg nullable 3필드 + prediction endpoint 신규.
- 결과(API 변경사항):
  - `RouteLegResponse`에 `transitionType: BOARDING|ALIGHTING|TRANSFER|BIKE_RENTAL|BIKE_RETURN | null`, `fromRentalId: string | null`, `toRentalId: string | null` 추가. 없으면 null (추측 금지).
  - `GET /api/bike-stations/{rentalId}/prediction?arrivalTime=` 신규.
    `{ status: AVAILABLE|UNAVAILABLE, predictedBikes: int>=0 | null, availabilityProbability: 0..1 | null, predictedAt | null, arrivalTime, rentalId, source: MODEL|MOCK }`.
    UNAVAILABLE는 예측값 전부 null (0으로 해석 금지).

## 참고 — 이미 반영済 (FE 문서가 구버전 기준이라 대조용)

- `GET /api/transit/arrivals?stationId&routeId` 구현済 (192). 응답은 `{ status: LIVE|NO_INFO|OUTSIDE_WINDOW|STALE, trains: [{trainId, direction, arrivalTime, updatedAt, source}], updatedAt }` 객체형. FE 문서의 배열형과 다름 — 사용 전 대조 필요.
- `POST /api/routes/replan` 구현済 (193). 요청 `{ step, boundaryId, destStationId(+좌표), modes, priority, requestedAt }`, 응답 `[{ reason, source, route(잔여 legs, totalMinutes=합±0.01) }]`. FE 문서의 풀형식과 다름 — 사용 전 대조 필요.
