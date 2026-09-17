# 컨슈머 백로그 따라잡기 — 밀린 이벤트를 얼마나 빨리 소화하는가

- 날짜 · 커밋: 2026-09-16 · `e46f41f` (브랜치 `feat/INFRA-realtime-consumer`, S15P21A104-171)
- 환경: 실습실 PC (Core Ultra 9 185H · RAM 63.5 GB) · Docker Desktop · `apache/kafka:4.2.1` · `redis:7` · 같은 머신, 로컬 직결
- 데이터 규모: `subway.arrival` **50,137건** (prod 덤프 한 회차 2,949건을 60초 간격으로 17배 재생 + 기존 IT 이벤트 4건)
- 조건: `max.poll.records=500` (운영과 같은 값), 파티션 1, 반영기 2개(지하철·따릉이)
- 반복: **1회** — 아래 "규약 충족 여부" 참고
- 외부 API 호출: **0회** (덤프 재생)

| 지표 | 값 |
| --- | --- |
| 총 소요 | 60,005 ms |
| 소화 | 50,137건 · 배치 137개 |
| Redis 쓰기 | 38,874회 |
| **처리량** | **초당 836건** |
| 배치 처리 시간 | min 95 · median 497 · p95 733 · max 1,819 ms |

명령:

```bash
# 백로그 쌓기 (로컬 compose 에만)
node BE/scripts/kafka/replay.mjs --dump .claude/perf/raw/subway-dump-2026-09-16.jsonl --times 17 --round \
  | docker exec -i sumgil-kafka /opt/kafka/bin/kafka-console-producer.sh \
      --bootstrap-server localhost:9092 --topic subway.arrival \
      --property parse.key=true --property key.separator=$'\t'

# 측정
PERF=1 PERF_TOPIC=subway.arrival KAFKA_BOOTSTRAP_SERVERS=localhost:9092 REDIS_HOST=localhost \
./gradlew test --tests '*ConsumerBacklogIT' -i
```

원본: 위 명령의 표준 출력 (`BE/src/test/java/.../consume/ConsumerBacklogIT.java`)

---

## 해석

**실부하 대비 약 17배 여유가 있다.** 실제 유입은 초당 약 50건(60초에 3,000건)인데 836건/초를 소화한다.
그래서 "버티는가" 는 질문이 안 되고, 쓸모 있는 답은 **장애 복구에 걸리는 시간**이다.

> 보관 48시간치(지하철 약 1.0M + 따릉이 약 0.9M ≈ **2.9M건**, [kafka.md](../infra/kafka.md) 4절 용량 계산)를
> 처음부터 따라잡으면 **약 58분**이다. 컨슈머가 하루 넘게 죽어 있어도 한 시간이면 복구된다는 뜻이다.
> (prod 는 파드 간 네트워크를 지나므로 이보다 느릴 수 있다 — 아래 "조건" 참고)

**병목은 Kafka 가 아니라 Redis 왕복이다.** 60초 동안 Redis 연산이 약 77,700회(쓰기 38,874 + 멱등 비교용 읽기 같은 수)로
초당 약 1,300회다. Redis 자체는 초당 10만 회급을 소화하므로 한계는 Redis 가 아니라 **연산을 하나씩 순차로 왕복하는 방식**이다
(연산당 약 0.77 ms). 파이프라이닝이나 `MGET`/`MSET` 으로 묶으면 크게 올릴 여지가 있다.

**다만 지금 올릴 이유가 없다.** 17배 여유가 있고, 이 구조를 바꾸면 멱등 비교(읽고 나서 쓰기)가 복잡해진다.
필요해지는 시점은 파티션을 늘려 처리량을 키울 때다 — 그때 이 문서의 숫자가 before 가 된다.

**파드를 늘려도 안 빨라진다.** 토픽이 전부 파티션 1이라(168) 같은 컨슈머 그룹에 둘을 띄우면 하나만 일한다.
처리량을 올리려면 파티션을 먼저 늘려야 한다 ([consumer.md](../infra/consumer.md) 4절).

## 규약 충족 여부

**이 기록은 1회 측정치다** — 워밍업 + 5회 반복(perf README 원칙 3)을 채우지 않았다.
백로그를 소화하면 오프셋이 소진돼 같은 조건을 다시 만들려면 5만 건을 매번 새로 적재해야 하기 때문이다.
따라서 **개선 근거로 인용하지 않는다.** 규모 감각과 복구 시간 산정용이다.

반복 측정이 필요해지면 매 회차 전에 토픽을 다시 채우는 절차를 스크립트로 묶어야 한다 (미착수).

## 읽지 말아야 할 숫자

측정 출력의 `배치별 consume 구간`(median 51,728 ms)은 **지연이 아니다.** 백로그를 60초에 걸쳐 소화하는 동안
"레코드가 브로커에 적힌 시각 → 우리가 쓴 시각" 이 계속 벌어지기 때문에 나오는 값으로, 백로그의 나이를 잰 것이다.
평상시 지연은 prod 에서 회차마다 남기는 로그로 따로 본다 ([consumer.md](../infra/consumer.md) 4절).

## 한 번 잘못 잰 기록

처음에는 `perf.backlog` 라는 별도 토픽에 쌓고 측정해 **초당 75,388건**이 나왔다. 그런데 반영기는 **Kafka 토픽 이름으로** 고르므로
`subway.arrival`·`bike.stock` 이 아닌 토픽은 전부 무시된다 — 5만 건을 읽고 Redis 쓰기가 0회였고, 잰 것은 루프 오버헤드였다.
`ConsumerBacklogIT` 에 "쓰기가 0회면 실패" 가드를 넣어 같은 실수가 조용히 지나가지 않게 했다.
