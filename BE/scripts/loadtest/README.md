# 로컬 부하 테스트 (S15P21A104-75)

실제 배포(사내 서버/클라우드) 전에, 로컬에서 먼저 성능 감을 잡기 위한 스크립트. `ab`/`wrk`/`k6` 같은
외부 도구 설치 없이 Node 내장 `fetch`만으로 동시 요청을 쏘고 지연시간(p50/p95/p99)·처리량·에러율을 집계한다.

## 실행

```bash
# BE 서버가 로컬에 떠 있는 상태에서
node scripts/loadtest/loadtest.mjs --base http://localhost:8080 --concurrency 50 --requests 1000
```

시나리오는 `routes/search`(단일 노선/환승 포함), `stations/search`, `bike-stations/nearby`를 번갈아 호출한다.

## 결과 (2026-09-10, 로컬 PC 기준)

| 동시성 | 총 요청 | 에러 | 처리량 | p50 | p99 |
| --- | --- | --- | --- | --- | --- |
| 10 | 200 | 0 | 168 req/s | ~25-95ms | ~75-245ms |
| 50 | 1,000 | 0 | 357 req/s | ~95-150ms | ~250-365ms |
| 150 | 1,500 | 0 | 424 req/s | ~300-350ms | ~630-705ms |
| 300 | 3,000 | 0 | 461 req/s | ~600-650ms | ~1,040-1,080ms |

**결론**
- 300 동시 요청까지 **에러 0건**. 처리량이 ~450~460 req/s에서 수렴하고 지연시간만 늘어나는(죽지 않고 줄서서 처리) 정상적인 포화 양상 — 발표/시연 규모(동시 사용자 소수)에는 문제없다.
- `stations/search`가 다른 엔드포인트보다 일관되게 느림(동시성 10에서 평균 107ms vs 나머지 27~43ms) — `StationSearchService`가 매칭된 역마다 노선 조회 쿼리를 따로 날리는 N+1 패턴이라서다(`RouteEdgeTimeRepository.findDistinctSubwayRouteIdsByStationId` + `RouteLineRepository.findById`를 역 개수만큼 반복 호출). 지금 트래픽 규모에선 문제 안 되지만, 결과가 많이 잡히는 검색어에서는 체감될 수 있어 기록해둔다 — 필요해지면 별도 최적화(배치 조회) 검토.
- HikariCP 커넥션 풀 관련 타임아웃·경합 로그 없음(기본 설정 그대로 사용 중).
