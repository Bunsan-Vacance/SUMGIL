# 재안내 규칙·에이전트 기준선 비교 결과 — S15P21A104-331

원본 수치는 `out/compare_<llm>.json`·`out/compare_<llm>.md`(스크립트가 매 실행마다 남긴다),
그림은 `figures/compare_<llm>.png`. 이 문서는 그 요약과 실행 조건을 기록한다(`AI/CLAUDE.md`
"결과 수치는 텍스트로 남긴다"). 지표 정의는 `README.md` 참고.

## fake 스모크 — 본 실행

`build_samples.py --n 8`(합성 표본, 시드 없이 결정적으로 8개 시나리오 각 1건) →
`compare.py --llm fake`(고정 지연 0ms) 1회 실행(2026-09-23, conda `SUMGIL`,
`PYTHONIOENCODING=utf-8`, 작업 디렉터리 `AI/`). 원본: `out/compare_fake.json`·
`out/compare_fake.md`, 그림 `figures/compare_fake.png`.

### 표본별

| id | 후보 | rule idx | agent idx | 일치 | recommended_by | reason 글자수 | reason 문장수 | LLM 지연(ms) | 전략 지연(ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s00_large_score_gap | 2 | 0 | 0 | O | AGENT | 58 | 1 | 0.0 | 0.15 |
| s01_small_score_gap | 2 | 0 | 0 | O | AGENT | 62 | 1 | 0.0 | 0.11 |
| s02_single_candidate | 1 | 0 | 0 | O | ALGORITHM | 67 | 2 | - | 0.01 |
| s03_near_risky_far_safe | 2 | 0 | 0 | O | AGENT | 59 | 1 | 0.0 | 0.12 |
| s04_many_candidates | 4 | 0 | 0 | O | AGENT | 61 | 1 | 0.0 | 0.09 |
| s05_proxy_predicted_stock | 2 | 1 | 1 | O | AGENT | 47 | 1 | 0.0 | 0.05 |
| s06_low_confidence_facts | 2 | 0 | 0 | O | AGENT | 60 | 1 | 0.0 | 0.06 |
| s07_three_candidates_close | 3 | 0 | 0 | O | AGENT | 60 | 1 | 0.0 | 0.07 |

### 집계

| 지표 | 값 |
| --- | --- |
| 일치율(전체 8건, 가드 탈락·후보 1개 포함) | 1.0 (8/8) |
| LLM이 실제로 채택된 표본(`recommended_by == AGENT`) | 7/8 |
| 그중 일치 | 7/7 |
| 가드 탈락 사유 분포 | 없음(8건 전부 탈락 없이 통과) |
| 입력/출력 토큰 합·평균 | None — fake는 토큰을 세지 않는다(`README.md` 지표 정의 참고) |
| LLM 지연 p50/p95(ms, 실제 호출 7건) | 0.0 / 0.0 |
| 에이전트 전략 전체 지연 p50/p95(ms) | 0.08 / 0.20 |
| 규칙 전략 전체 지연 p50/p95(ms) | 0.01 / 0.02 |

**읽는 법**: 일치율 100%는 기대한 결과다(`README.md` "fake 클라이언트" 절) — fake가 규칙의
선택을 그대로 따라 하고 이유도 후보 설명에서 그대로 인용하므로 환각 검사를 전부 통과한다.
`s02`(후보 1개)만 `recommended_by=ALGORITHM`인 이유는 `AgentStrategy`가 후보 1개일 때 LLM을
아예 안 부르고 규칙 폴백을 바로 쓰기 때문이다(`llm_called=false`, `llm_latency_ms=None`) — 이
표본은 "판단이 일치했다"가 아니라 "애초에 LLM이 관여하지 않았다"로 읽는다. 이 스모크의 목적은
**배관(파싱·가드·집계·그림 생성)이 실제 게이트웨이 없이 끝까지 도는지 확인하는 것**이지, 규칙과
에이전트의 실제 판단 차이를 재는 것이 아니다 — 그 수치는 아래 real 절에서 나온다.

## real — 미측정

이 세션에서는 **`--llm real`을 실행하지 않았다**(`AI/CLAUDE.md` 하드 룰 — 표본 수만큼 실제 LLM
게이트웨이를 호출하는 스크립트라 실행 범위를 사용자와 먼저 맞춰야 한다, `README.md` "실행" 절).
사용자 확인 후 아래를 채운다.

| 지표 | 값 |
| --- | --- |
| 일치율(전체) | 미측정 |
| LLM이 실제로 채택된 표본 중 일치 | 미측정 |
| 가드 탈락 사유 분포 | 미측정 |
| 입력/출력 토큰 합·평균 | 미측정 |
| LLM 지연 p50/p95(ms) | 미측정 |
| 에이전트 전략 전체 지연 p50/p95(ms) | 미측정 |

**판정(미측정 채운 뒤 작성)**. real 일치율과 fake 스모크(100%, 배관 확인용)를 나란히 놓고 "실제
판단이 얼마나 갈리는지"를 여기 적는다. 토큰·지연 수치는 이후 토큰 최적화 후보(max_tokens 상한·
후보 상한 K·시스템 프롬프트 압축, `plans/TIME-331-harness-plan.md` 3단계)의 채택 판정 기준선이
된다.
