# 재안내 성능 측정 결과 — S15P21A104-323-4

원본 수치는 `out/*.json`·`out/*.md`(스크립트가 매 실행마다 남긴다). 이 문서는 그 요약과 실행
조건을 기록한다. 계약 기준: **FE 타임아웃 6초**(`README.md` 참고).

## 로컬(가짜 BE·가짜 LLM·가짜 색인) — 본 측정

미측정. `python validation/TIME/latency-check/src/run_local.py --sessions {10|50|100} --rounds 3`
를 각각 실행한 뒤 아래 표를 채운다.

| sessions | rounds | LLM 고정 지연(ms) | 경로 | n | p50(ms) | p95(ms) | 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 3 | 1200 | no_trigger | 미측정 | 미측정 | 미측정 | |
| 10 | 3 | 1200 | proposal(전체) | 미측정 | 미측정 | 미측정 | |
| 10 | 3 | 1200 | proposal(오버헤드=전체−LLM) | 미측정 | 미측정 | 미측정 | |
| 50 | 3 | 1200 | no_trigger | 미측정 | 미측정 | 미측정 | |
| 50 | 3 | 1200 | proposal(전체) | 미측정 | 미측정 | 미측정 | |
| 50 | 3 | 1200 | proposal(오버헤드=전체−LLM) | 미측정 | 미측정 | 미측정 | |
| 100 | 3 | 1200 | no_trigger | 미측정 | 미측정 | 미측정 | |
| 100 | 3 | 1200 | proposal(전체) | 미측정 | 미측정 | 미측정 | |
| 100 | 3 | 1200 | proposal(오버헤드=전체−LLM) | 미측정 | 미측정 | 미측정 | |

**판정(미측정 채운 뒤 작성).** `proposal` p95가 6초를 넘는 세션 수가 있는지, 오버헤드가 세션
수에 비례해 늘어나는지(스레드풀·GIL 경합 신호)를 여기 적는다.

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

## 배포 서버 — 미측정

`run_dev.py`는 이 세션에서 작성만 하고 실행하지 않았다(`README.md` "실행" 절 참고 — 배포 서버에
반복 호출을 보내려면 실행 범위를 먼저 사람과 맞춰야 한다). 실행 후 아래를 채운다.

| base_url | count | concurrency | with_proposal | n | p50(ms) | p95(ms) | 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 미측정 | | | | | | | |
