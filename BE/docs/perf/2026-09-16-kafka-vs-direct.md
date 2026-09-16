# 수집기 회차 내보내기 — Kafka 경유 vs Redis 직접 쓰기

- 날짜 · 커밋: 2026-09-16 · `e46f41f` (브랜치 `feat/INFRA-realtime-consumer`, S15P21A104-171)
- 환경: 실습실 PC (Core Ultra 9 185H · RAM 63.5 GB) · Docker Desktop · `apache/kafka:4.2.1` · `redis:7` · 같은 머신, 로컬 직결
- 데이터 규모: `subway.arrival` 한 회차 **2,949건** (prod 덤프 `poll_run_at=2026-09-16T10:46:57+09:00`). 두 조건에 **같은 목록**을 넣는다
- 반복: 조건별 워밍업 1회 + 측정 5회
- 외부 API 호출: **0회** (이미 Kafka 에 쌓인 회차를 덤프해 재생 — 하루 1,000회 예산을 쓰지 않는다)

| 조건 | 스위치 | 지표 | min | median | p95 | max |
| --- | --- | --- | --- | --- | --- | --- |
| Kafka 경유 (브로커에 넘기기까지) | `collect.publisher=kafka` | 회차 소요(ms) | 61 | **66** | 88 | 88 |
| Redis 직접 (반영까지 끝) | `collect.publisher=redis` | 회차 소요(ms) | 408 | **546** | 636 | 636 |

명령:

```bash
PERF=1 PERF_DUMP=.claude/perf/raw/subway-dump-2026-09-16.jsonl \
KAFKA_BOOTSTRAP_SERVERS=localhost:9092 REDIS_HOST=localhost \
./gradlew test --tests '*PublisherBenchmarkIT' -i
```

원본: 위 명령의 표준 출력 (`BE/src/test/java/.../consume/PublisherBenchmarkIT.java`)

---

## 해석

**이 숫자를 "Kafka 가 8배 빠르다" 로 읽으면 안 된다.** 두 조건이 하는 일의 양이 다르다.
Kafka 경유는 회차를 브로커에 넘기면 끝이고, 실제 Redis 반영은 컨슈머가 따로 한다.
Redis 직접은 같은 66ms 안에 끝나는 게 아니라 **2,949건을 역 단위로 묶어 Redis 에 읽고 쓰는 것까지** 546ms 안에 다 한다.
허수아비 비교(perf README 원칙 4)를 피하려면 이 차이를 함께 적어야 한다.

**이 측정의 쓸모는 두 가지다.**

1. **수집기가 회차 주기를 지킬 여유가 있는가.** 지하철 주기가 60초인데 어느 쪽이든 1초 미만이다. 둘 다 여유가 크다 —
   즉 **보험 스위치를 돌려도 수집기는 버틴다.** 이것이 스위치를 남긴 목적(티켓 본문 "Kafka 장애 시 발표 직전 회귀용")을 뒷받침한다.
2. **Kafka 를 끼우는 비용의 상한.** 수집기 쪽에서 Kafka 가 더하는 것은 회차당 66ms 수준이다.
   전체 지연(이벤트가 Redis 에 보이기까지)은 여기에 컨슈머 몫이 더 붙는다 — 아래 참고.

**Kafka 의 값어치는 이 표에 안 나온다.** 직접 쓰기로 바꾸면 AI 파트(`ai-spark` 그룹)가 **아무 이벤트도 받지 못하고**,
컨슈머가 죽어 있는 동안 들어온 것도 유실된다(Kafka 면 48시간 보관분을 따라잡는다). 지연으로는 잴 수 없는 항목이라
장애 실험으로 따로 봐야 한다.

## 아직 안 잰 것

**end-to-end 지연** (`ingested_at` → Redis 에 보이기까지)은 여기서 안 나온다. Kafka 경로는 컨슈머가 따로 돌아야 완성되기 때문이다.
컨슈머가 회차마다 두 구간을 로그로 남기도록 해뒀다 — prod 배포 뒤 며칠이면 60초 주기로 표본이 저절로 쌓인다.

```
ingested_at ──────→ 레코드 timestamp ──────→ written_at
     (produce 구간)          (consume 구간)
```

그때 이 문서에 세 번째 표를 붙인다. 그 전까지는 **prod 의 end-to-end 지연 수치를 인용하지 않는다.**

## 조건이 다른 수치와 나란히 놓지 않는다

- 173 의 prod 첫 회차 수치(지하철 3,914ms 등)는 **1회 관측치**이고 EC2·k3s 조건이라 위 표와 비교하지 않는다 (원칙 5).
- 위 표는 로컬 직결이다. prod 는 파드 간 네트워크를 지나므로 그대로 옮겨 쓸 수 없다.
