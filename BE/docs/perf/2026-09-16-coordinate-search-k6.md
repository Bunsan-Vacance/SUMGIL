# 좌표 기반 경로 검색 k6 부하테스트 — 그래프 전체 복사 병목 발견

- 날짜: 2026-09-16 (미커밋 상태, 브랜치 `feat/ROUTE-coordinate-access-search`)
- 환경: 로컬 PC · Docker(postgres:16 · redis:7) · BE 로컬 `bootRun`
- 대상: `POST /api/routes/search/coordinate` (S15P21A104-154)
- 도구: k6(`GrafanaLabs.k6`), 스크립트 `BE/scripts/loadtest/k6-coordinate-search.js`
- 반복: 1회 (규약 미충족 — 아래 "정식 기록 전환 시 필요한 것" 참고)

## 결론 먼저

**검색 로직(정확성)은 문제없다.** 에러율 0%, 응답 상태코드 전부 200/404로 정상. 문제는 **성능**이다 — 좌표 검색 요청마다 전체 그래프(역 16,189개 · 엣지 224,184개)를 통째로 복사하는 구현 방식이 병목이다. 단일 요청도 기본 776ms가 걸려, 동시성 30에서 p95 13.43초까지 치솟았다.

## 실행 조건

```bash
k6 run BE/scripts/loadtest/k6-coordinate-search.js
```

- 시나리오: 역삼·강남·신촌·잠실·건대입구·홍대입구 실좌표 6곳을 "건물 위치"처럼 써서 매번 다른 출발·도착 조합으로 호출
- 부하 패턴: 20초 웜업(최대 15 VU) → 1분 본 부하(최대 30 VU) → 20초 램프다운
- threshold: 실패율 1% 미만, p95 응답 2초 미만

## 결과

| 지표 | 값 |
| --- | --- |
| 총 요청 | 376건 |
| 에러율 | 0.00% |
| 응답 최소 | 776.76ms |
| 응답 중앙값 | 2.53s |
| 응답 p90 | 11.54s |
| **응답 p95** | **13.43s (threshold 2s 미달 — FAIL)** |
| 응답 최대 | 16.66s |
| 처리량 | 3.65 req/s |
| 후보 개수(평균) | 3.16개 |
| 접근후보없음(404) 비율 | 0.00% |

threshold 판정: `http_req_failed rate<0.01` 통과, `http_req_duration p(95)<2000` **실패**.

## 원인 분석

`RouteGraph.withExtraEdges()`가 요청마다 원본 그래프 전체를 두 번 깊은 복사한다.

```java
public RouteGraph withExtraEdges(List<Edge> extraEdges) {
    ...
    Set<String> newNodes = new LinkedHashSet<>(nodes);              // 역 16,189개 복사
    adjacency.forEach((node, edges) -> newAdjacency.put(node, new ArrayList<>(edges))); // 엣지 224,184개 전부 복사
    stationLines.forEach((node, lines) -> newLines.put(node, new LinkedHashSet<>(lines)));
    ...
    return RouteGraph.of(newNodes, newAdjacency, newLines);         // RouteGraph.of 내부에서 또 한 번 전체 복사
}
```

- `searchByCoordinate`는 접근 후보 임시 WALK 엣지(요청당 최대 10개)를 붙이려고, 22만 엣지짜리 전체 그래프를 두 번 복사한 뒤에야 기존 다중 후보 탐색(`algorithmCandidates`, 7개 하위 그래프 조합 × `filterByModes`)으로 넘어간다.
- 단일 요청 최소값(776ms)부터 이미 느리다는 게 핵심 근거 — 동시성이 0에 가까워도 기본 비용이 크다는 뜻이라, 서버를 여러 대로 늘리는(분산) 방식으로는 해결되지 않는다. 동시 요청이 늘면 이 무거운 복사 작업들이 CPU를 놓고 경쟁하며 큐잉 지연이 커진다(중앙값 2.53s → p95 13.43s로 벌어지는 패턴과 일치).
- 기존 역 ID 검색(`GET /api/routes/search`)은 이 복사 단계가 없어 동시성 300에서도 p99 ~1초였다(`scripts/loadtest/loadtest.mjs` 2026-09-10 기록, 이 문서와 나란히 비교 불가 — 조건 다름, 감각용 참고만).

## 다음 조치 (미착수) — 실행됨, 아래 "1차 최적화 후 정정" 참고

- `withExtraEdges`가 전체 그래프를 복사하지 않고, 임시 접근 노드 몇 개만 얹는 가벼운 오버레이 구조로 바꾸는 최적화 필요 — 아래에서 실행함.
- 최적화 후 같은 스크립트로 재측정해 before/after 비교 필요.

## 1차 최적화 후 정정 — 원인 진단이 틀렸음을 확인

`withExtraEdges`를 얕은 복사(맵 항목만 O(V)로 복사, 값은 불변이라 재사용)로 바꾸고 재측정했는데, **오히려 더 나빠졌다**(p95 13.43s → 18.6s, 최소값 776ms → 738ms로 거의 그대로).

이상해서 **좌표 검색이 아닌 기존 역 ID 검색(`GET /api/routes/search?originStationId=221&destStationId=222`)만 동시성 0으로 단독 호출**해봤다:

```
요청 1: 1875ms
요청 2: 1407ms
요청 3: 1666ms
```

**`withExtraEdges`를 전혀 안 타는 기존 역 검색도 이미 1.4~1.9초씩 걸린다.** 즉 `withExtraEdges`의 그래프 전체 복사는 병목의 일부였을 수는 있어도 **주된 원인이 아니었다** — 좌표 검색·역 검색이 공유하는 다른 곳이 진짜 원인이다.

**유력한 진짜 원인**: `RouteSearchService.algorithmCandidates()`가 요청마다 `CANDIDATE_CORE_MODE_SETS`(7개 수단 조합)만큼 `graph.filterByModes(...)`를 호출한다 — 매번 전체 엣지(`edges()`)를 훑어 하위 그래프를 다시 조립한다. 이 구조 자체는 2026-09-10에 그래프가 훨씬 작을 때(역 564개·엣지 12,626개, `scripts/loadtest/loadtest.mjs` 기록) 측정해 문제없다고 판단했던 것인데, **그 이후 팀원들이 버스·전체 지하철망을 merge하면서 지금 그래프는 역 16,189개·엣지 224,184개로 그때보다 약 18배 커졌다.** 이후 이 부분 성능을 재측정한 적이 없었다.

즉 "요청마다 22만 엣지짜리 그래프를 7번씩 훑어 하위 그래프를 다시 만드는" 구조가, 커진 그래프 크기에서는 좌표 검색뿐 아니라 **기존 역 ID 검색을 포함한 전체 경로 검색 API**를 느리게 만들고 있다는 뜻이다. 범위가 "좌표 검색만의 문제"에서 "경로 검색 전체의 문제"로 커졌다.

**교훈**: 최적화 전에 "다른 요인이 섞이지 않은 대조군"(여기서는 좌표 검색 없이 순수 역 검색만)을 먼저 확인했어야 했다. `withExtraEdges`가 무거워 보인다는 코드 리딩만으로 원인을 단정하고 고쳤다가, 실측(재측정)에서야 틀렸다는 게 드러났다 — 코드를 보고 세운 가설은 반드시 대조 실험으로 검증해야 한다는 사례.

## 2차 최적화 — 조합별 하위 그래프를 로드 시점에 캐싱

`CANDIDATE_CORE_MODE_SETS`(`CandidateModeSets.CORE_MODE_SETS`로 이동) 7개 조합에 대한 하위 그래프를 요청마다 `graph.filterByModes(...)`로 다시 만들지 않고, `RouteGraphRegistry` 기동 시(`@PostConstruct`) 1회만 계산해 `candidateSubgraphs()`로 캐싱했다. 역 검색은 이 캐시를 그대로 쓰고, 좌표 검색은 캐시된 7개 하위 그래프 각각에 접근 임시 엣지(`withExtraEdges`, 1차 최적화로 이미 가벼워짐)만 얹는다.

같은 k6 스크립트로 재측정(단일 요청 3회 + k6 30 VU 부하):

| 지표 | 1차 시도 후(원인 오판) | 2차 최적화 후 | 개선폭 |
| --- | --- | --- | --- |
| 단일 요청(역 검색, 동시성 0) | 1,407~1,875ms | **229~290ms**(웜업 후) | 약 5~6배 |
| 단일 요청(좌표 검색, 동시성 0) | (k6 min 738ms) | **304~387ms**(웜업 후) | 약 2배 |
| k6 최소 응답 | 737.89ms | **147.14ms** | 5배 |
| k6 중앙값 | 2.84s | 2.23s | — |
| **k6 p95** | 18.6s | **4.66s** (threshold 2s 여전히 미달) | 약 4배 |
| k6 최대 | 22.59s | 9.65s | 약 2.3배 |
| 처리량 | 3.08 req/s | 6.65 req/s | 약 2배 |

**정리**: 실제로 크게 개선됐다(최소값 5배, p95 4배, 처리량 2배) — 근본 원인(요청마다 22만 엣지 그래프를 7번 필터링)을 정확히 짚었다는 증거다. 다만 threshold(p95 2초 미만)는 아직 못 넘겼다 — 동시성 30에서 여전히 큐잉 지연이 남아있다(중앙값이 단일 요청 대비 훨씬 높음). 그래프 자체가 상당히 큰 상태(엣지 22만 개)에서 `ShortestPathFinder`(Dijkstra) 자체의 반복 비용, GC 압력, Tomcat 스레드풀 크기 등 추가 요인이 남아있을 수 있어 후속 조사가 필요하다.

## 정식 기록 전환 시 필요한 것 (perf 기록 규약 참고)

이 문서는 **1회 측정치**라 "개선 근거"로 인용하지 않는다(`docs/perf/README.md` 원칙 3). 정식 기록으로 남기려면:
- 워밍업 1회 + 5회 반복, median·p95로 재정리
- 최적화 전/후를 같은 조건(같은 VU·DURATION, 같은 그래프 스냅샷)에서 나란히 측정
- 원본 k6 콘솔 출력은 `.claude/perf/raw/2026-09-16-coordinate-search-k6.log`에 저장(Git 제외)
