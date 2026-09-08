# 성능 측정 기록 규약

> C 파트(외부 연동·적재·수집기·Kafka)의 "개선 전·후" 수치를 남기는 자리다.
> 기능 MR에 측정 파일이 함께 실려 오면 리뷰어가 코드와 숫자를 같은 커밋에서 대조할 수 있다.

## 원칙

1. **단순한 버전을 먼저 만들고 그 상태를 측정한 뒤 개선한다.** 순진한 구현이 곧 baseline이다. 개선 뒤에 "예전 방식은 아마 느렸을 것"이라고 쓰지 않는다.
2. **예전 경로는 지우지 않고 스위치(환경변수·플래그)로 남긴다.** 스위치만 바꿔 before와 after를 같은 조건에서 다시 측정할 수 있어야 한다.
3. **같은 조건, 여러 번, 분포로 측정한다.** 같은 머신, 같은 데이터 스냅샷, 워밍업 1회 뒤 5회 이상 반복. 평균이 아니라 **중앙값과 p95**를 적는다.
4. **개선율만 쓰지 않고 절대값과 조건을 함께 쓴다.** 행 수, 머신, 도커 자원 제한까지 붙인다. 허수아비 비교(아무도 안 쓰는 방식을 before로 세우기)는 하지 않는다.

## 파일 규칙

- 실험 1건 = 파일 1개. 이름은 `YYYY-MM-DD-<주제>.md` (예: `2026-09-10-edge-time-batch-load.md`).
- 저장소에는 **요약 표만** 커밋한다. psql 출력, probe JSONL, 로그 같은 **원본 출력은 `.claude/perf/raw/`** (Git 제외)에 두고 파일명을 표에 적는다.
- 팀 발표에 쓰는 수치는 Notion에도 옮긴다. 정본은 이 폴더다.

## 기록 항목

| 항목 | 내용 |
| --- | --- |
| 날짜 · 커밋 | 측정한 날짜와 `git rev-parse --short HEAD` |
| 환경 | 머신(CPU·RAM), OS, Docker 자원 제한, PostgreSQL·Redis·Kafka 버전 |
| 데이터 규모 | 행 수, 파일 크기, 호출 건수 등 |
| 조건 | before / after 각각의 스위치 값, 파라미터 |
| 명령 | 재현에 필요한 정확한 명령 |
| 반복 | 워밍업 포함 회수 |
| 결과 | 지표별 min · median · p95 · max |
| 원본 | `.claude/perf/raw/` 안의 파일명 |

## 템플릿

```markdown
# <주제>

- 날짜 · 커밋: 2026-09-10 · abc1234
- 환경: <머신> · Docker <자원 제한> · postgres:16 · redis:7
- 데이터 규모: edge_time 103,680행 (720 엣지 × 48 슬롯 × 3 요일)
- 반복: 워밍업 1회 + 5회

| 조건 | 스위치 | 지표 | min | median | p95 | max |
| --- | --- | --- | --- | --- | --- | --- |
| before: 행 단위 INSERT | LOAD_MODE=row | 총 소요(s) | | | | |
| after: JDBC batch | LOAD_MODE=batch | 총 소요(s) | | | | |

명령: `...`
원본: `.claude/perf/raw/2026-09-10-edge-time-*.log`
해석: <무엇이 달라졌고 왜인지 두 문장>
```

## 도구

| 대상 | 도구 |
| --- | --- |
| 외부 API 응답 시간·크기 | `node BE/scripts/external/probe.mjs <source> --repeat 5 --jsonl .claude/perf/raw/<파일>.jsonl` |
| 적재 처리량 | 적재 스크립트의 자체 타이머 + `psql`의 `\timing`, 행 수는 `SELECT count(*)` |
| 쿼리 | `EXPLAIN (ANALYZE, BUFFERS)` |
| 어댑터·수집기 지연 | 이벤트의 `source_generated_at` · `ingested_at` · `written_at` 세 시각 차이. Java면 Micrometer 타이머(Actuator 포함) |
| Kafka | `kafka-consumer-groups --describe` 의 LAG, 컨슈머 로그의 중복 제거·덮어쓰기 차단 카운터 |
| 장애 주입 | 키 무효화 · 오래된 값 주입 · Redis 다운 상태에서 100회 요청, 성공률과 p95 |
