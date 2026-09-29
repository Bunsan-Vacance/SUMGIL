# 경로 탐색 통합 검증 기준선 — 단위 레벨 탐색량·지연

- 날짜: 2026-09-18 (브랜치 `feat/ROUTE-integration-verify`, S15P21A104-194)
- 환경: 로컬 PC · DB·Redis 없이 · 인메모리 그래프 · 외부 API 호출 0건 (noop 레지스트리)
- 대상: `RouteSearchService.search` (213·214·190 반영 후: K-path + 6경로 + 슬롯 그래프 + 첫 승차 대기)
- 도구: `SearchBaseline194Test` (JUnit, 웜업 5회 + 측정 20회)
- 반복: 1회 (단위 기준선 — prod 실측 아님)

## 결론 먼저

**탐색 로직(정확성)은 문제없다.** 8종 시나리오(장소OD·버스환승·순수도보·수단제외·동일좌표·후보없음·geometry누락·시간경계) 전부 기존 테스트로 커버되고 green이다. 성능은 **100정점 그래프에서 p95 25ms** — k6 실서버 측정(2026-09-16, p95 13.43s FAIL)과 단위가 다르다. 그때 병목(전체 그래프 복사)은 `withExtraEdges` 얕은 복사로 해소済. 실서버 기준선은 167 prod 적재 후 별도 측정한다.

## 실행 조건

```powershell
.\gradlew test --tests 'com.ssafy.s15p21a104.domain.route.service.SearchBaseline194Test' --rerun-tasks --console=plain -q
```

- 그래프: 100개 정점 체인(S0→S100, 엣지당 100초) + 지름길 10개(L2, 200초)
- 측정: S0→S100 탐색 20회, geometry는 unavailable (외부 호출 없음)

## 결과

| 지표 | 값 |
| --- | --- |
| p50 | 20ms |
| p95 | 25ms |
| max | 27ms |
| 후보 수 | 1개 이상 |
| 외부 호출 | 0건 (geometry 전부 unavailable) |

## 탐색량 분석

- K-path spur 분기: 후보 K개당 최대 (경로 길이 × 확정 수)회 `single.find` 호출. 100정점 체인에서 실측 20~27ms.
- 슬롯 그래프: `graphFor` 캐시 적중 시 O(1). 미적중 시 슬롯별 SUBWAY 행 조회 1회 + 조립 1회.
- geometry 후처리: 후보별 병렬 (virtual thread). noop 기준 측정 제외 — 카카오 latency는 별도 (키 미발급).
- 외부 호출수: 탐색 경로에서 DB·Redis·AI·카카오 호출 0건. 혼잡 조회는 `congestionRepository` 1회/노선 (후보 확정 후, 6개 이하).

## 오류 vs 정상 빈결과 구분

| 상황 | 응답 | 코드 |
| --- | --- | --- |
| 출발=도착 | 오류 | SAME_ORIGIN_DEST |
| 미등록역 | 오류 | STATION_NOT_FOUND |
| 그래프 미적재 | 오류 (503) | ROUTE_DATA_NOT_READY |
| 연결 불가 | 정상 빈 배열 | 200 + `[]` |
| 접근 후보 없음 (좌표) | 오류 (404) | ACCESS_CANDIDATE_NOT_FOUND |
| 좌표 무효 | 오류 | INVALID_COORDINATE |

## 미지원 경로 / 제공자 한계

- `SHORTEST_WITH_BIKE` enum 존재하나 생성 코드 없음 — 응답에 안 나온다.
- 혼잡 데이터 없으면 혼잡 3은 빈 목록 (속도 3만 응답).
- 실시간 도착값 미반영 — 정적 슬롯 기준선만. 실시간은 정적 기준선 이후 협의 (190 범위 밖).
- 출발 시각대별 대기시간 원천 (`waitSec`) — edge_time 적재값 그대로. 원천 없으면 0 (날조 없음).

## 다음 조치

- 167 prod 적재 후 실서버 k6 재측정 (이 문서와 동일 조건 비교 불가 — 단위 vs 실서버).
- 카카오 키 발급 후 geometry latency 별도 측정 (186).
