# 재안내 성능 측정 결과 — S15P21A104-323-4

원본 수치는 `out/*.json`·`out/*.md`(스크립트가 매 실행마다 남긴다). 이 문서는 그 요약과 실행
조건을 기록한다. 계약 기준: **FE 타임아웃 6초**(`README.md` 참고).

## 로컬(가짜 BE·가짜 LLM·가짜 색인) — 본 측정 (2026-09-23)

`run_local.py --sessions {10|50|100} --rounds 3`, LLM 고정 지연 1,200ms. 원본 `out/local_s<N>_r3.{json,md}`(gitignore).
측정 전에 가짜 BE의 `replan` 응답을 첫 leg BIKE·`boundary_id` 출발로 고쳤다 — 324 첫 leg 검증 가드가
들어간 뒤로는 출발 노드가 없는 가짜 경로가 전부 `unavailable`로 떨어져 proposal 지연을 잴 수 없었다.

| 세션 | 라운드 | 표본 | 경로 | p50(ms) | p95(ms) | max(ms) | status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 3 | 30 | no_trigger | 6.6 | 12.2 | 21.6 | no_trigger 30 |
| 10 | 3 | 30 | proposal(전체) | 1,209.8 | 1,232.4 | 1,232.9 | proposal 30 · AGENT 30 |
| 10 | 3 | 30 | proposal(오버헤드=전체−LLM) | 9.8 | 32.4 | | |
| 50 | 3 | 150 | no_trigger | 15.8 | 23.5 | 28.1 | no_trigger 150 |
| 50 | 3 | 150 | proposal(전체) | 1,217.6 | 2,388.5 | 2,392.9 | proposal 150 · AGENT 150 |
| 50 | 3 | 150 | proposal(오버헤드=전체−LLM) | 17.6 | 1,188.5 | | |
| 100 | 3 | 300 | no_trigger | 25.1 | 36.6 | 42.8 | no_trigger 300 |
| 100 | 3 | 300 | proposal(전체) | 2,418.6 | 3,580.6 | 3,588.5 | proposal 300 · AGENT 300 |
| 100 | 3 | 300 | proposal(오버헤드=전체−LLM) | 1,218.6 | 2,380.6 | | |

**판정.**

- **`no_trigger` 경로는 문제 없다.** 100세션 동시 폴링에서도 p95 37ms. 실제 폴링(120초 주기)에서는 100세션이 동시에 몰리는 일 자체가 드물다.
- **`proposal` 경로의 p95는 세션 수에 따라 1.2초 단위로 계단식 증가한다** — 10세션 1.23초, 50세션 2.39초, 100세션 3.58초. 오버헤드(전체−LLM)가 10세션에서 32ms인데 100세션에서 2.38초로 뛰는 것은 코드 오버헤드가 아니라 **대기열**이다. `check_reroute`가 동기 엔드포인트라 Starlette가 스레드풀(anyio 기본 40 토큰)에서 돌리고, LLM 1.2초 동안 스레드가 묶이므로 동시 proposal이 40을 넘으면 다음 물결로 밀린다(50세션=2물결 2.4초, 100세션=3물결 3.6초와 정확히 맞는다).
- **6초 계약 안에 드는 동시 proposal 상한은 약 160건**(4물결 4.8초 + 오버헤드). 실제로는 트리거가 서는 세션만 LLM을 부르고 세션 예산(3회)도 있어 동시 proposal이 수십 건을 넘기 어렵다. 지금 구조로 충분하다.
- 동시 LLM 호출이 40을 넘을 전망이 생기면 선택지는 둘이다 — (a) 엔드포인트를 `async def`로 바꾸고 LLM·BE 호출을 비동기 HTTP 클라이언트로(스레드풀 상한 해제), (b) anyio 스레드풀 토큰 상향. (a)가 맞지만 이번 스프린트 범위 밖이다.
- 이 수치는 가짜 LLM(고정 1.2초, 331 real 실측 p50 1.4~1.7초와 근접)·가짜 BE(즉시 응답, dev 실측 0.75초) 기준이다. 배포 서버 측정에서는 BE 0.75초가 proposal 경로에 더해진다.

## 로컬 — 스모크(로컬, 가짜 BE·LLM)

`python validation/TIME/latency-check/src/run_local.py --sessions 10 --rounds 1` 1회 실행
(2026-09-23 10:44 KST, conda `SUMGIL`, `PYTHONIOENCODING=utf-8`). 원본:
`out/local_s10_r1.json`·`out/local_s10_r1.md`.

| 경로 | n | mean(ms) | p50(ms) | p95(ms) | min(ms) | max(ms) | status/recommendedBy |
| --- | --- | --- | --- | --- | --- | --- | --- |
| no_trigger | 10 | 13.2 | 11.5 | 19.1 | 8.1 | 20.3 | no_trigger ×10 |
| proposal(전체) | 10 | 1206.0 | 1206.3 | 1207.7 | 1203.4 | 1207.9 | proposal ×10, AGENT ×10 |
| proposal(오버헤드=전체−LLM 1200ms) | 10 | 6.0 | 6.3 | 7.7 | | | |

10개 세션 전부 `proposal`로 끝났고(폴백 없이 가짜 LLM 응답이 환각 검사를 전부 통과), 오버헤드
(트리거 판정·후보 탐색·프리페치·경로 연결·도보 합성 합)는 p95 기준 8ms 미만 — 가짜 BE·색인이
전부 인메모리라 이 스모크에서는 LLM 고정 지연(1.2초)이 `proposal` 총 지연의 사실상 전부다.
세션 수를 올렸을 때(50·100) 이 오버헤드가 그대로 유지되는지가 본 측정의 핵심 관전 포인트다
(스레드풀 경합이 있으면 오버헤드가 세션 수에 비례해 늘어난다).

## 로컬 실색인·실BE — E2E·본 측정 (2026-09-26, S15P21A104-301)

배포 서버(`/ai/**`)가 아직 없어, **실제 스냅샷·실제 모델·실제 dev BE**를 붙인 로컬 uvicorn을 배포 서버 대신 쟀다.
가짜였던 것은 없다 — LLM만 규칙 전략(`ALGORITHM`, `TIME_LLM_MODEL` 비움)이라 호출되지 않는다.

- 색인: J15A104A `latest_stock.parquet`(7컬럼, 컨슈머 반영 후) 2,744행 → 좌표 있는 2,345곳. 신선도 300초라 측정 직전 scp.
- 예측: `models/BIKE/v4-weather-final_20260917-2037` + `station_master.parquet` + `latest_weather.parquet`(서버에서 복사). `lag_lookup_live.parquet`은 서버에도 없어 모델은 lag 없이 돌았다(`source=lightgbm`).
- BE: `TIME_BE_BASE_URL=https://j15a104.p.ssafy.io` 실 `replan`. 대여소 노드(`ST-*`)→역 `239`(홍대입구)가 그래프에 있어 첫 leg `BIKE` 경로가 온다.
- 시연 override: `TIME_DEBUG_FORCE_TRIGGER_ENABLED=1 TIME_DEBUG_EMPTY_RENTAL_IDS=ST-145`.

### E2E 3상태 (curl 1회씩)

| 요청 rentalId | 상태 | reason | 비고 |
| --- | --- | --- | --- |
| `ST-1947`(재고 37) | `no_trigger` | `below_threshold` | 실예측 p_empty 0.04 |
| `ST-145`(override) | `proposal` | 규칙 문장 | target predictedStock 0.0·pEmpty 1.0(override), 대안 `ST-144` 탑골공원 앞 214m(실예측 7.9대), route = dev BE 실경로, 1.6초 |
| `ST-NOPE` | `unavailable` | `target_unknown` | 색인에 없음 |

### 본 측정 (`run_dev.py --base-url http://localhost:8000 --count 20 --concurrency 1`)

| 경로 | p50 | p95 | max | body.status |
| --- | --- | --- | --- | --- |
| `no_trigger` (`ST-1947`) | 232ms | 401ms | 2,285ms(첫 호출 워밍업) | no_trigger 20/20 |
| `proposal` (`--with-proposal`, `ST-1947` 강제) | 1,883ms | 2,182ms | 4,118ms(첫 호출) | proposal 20/20 |

판정: 둘 다 6초 계약 안. `proposal` 1.9초의 구성은 대상 예측 1회(≈0.23초) + 후보 최대 5곳 예측(각 ≈0.23초, 순차) + BE replan(≈0.75초)로 설명된다 — LightGBM 예측이 대여소마다 따로 도는 것이 가장 큰 몫이라, 줄이려면 후보 예측을 한 번에 배치로 묶는 것이 다음 최적화 후보다(이번 범위 밖). 결과 파일 `out/dev_no_trigger_n20_c1.*`·`out/dev_proposal_n20_c1.*`, 시나리오 표 `out/scenario_20260926.md`(실고갈 160곳·강제용 2,016곳, 조회 약 4분 — 색인을 대여소마다 다시 만드는 구조라 느리다).

## 배포 서버 — 미측정 (2026-09-23 확인: `/ai/**`가 FE index.html로 떨어짐 — INFRA AI Ingress 미배포. Ingress 머지·AI 이미지(211) 후 `run_dev.py --base-url https://j15a104.p.ssafy.io/ai` 1회)

`run_dev.py`는 이 세션에서 작성만 하고 실행하지 않았다(`README.md` "실행" 절 참고 — 배포 서버에
반복 호출을 보내려면 실행 범위를 먼저 사람과 맞춰야 한다). 실행 후 아래를 채운다.

| base_url | count | concurrency | with_proposal | n | p50(ms) | p95(ms) | 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 미측정 | | | | | | | |
