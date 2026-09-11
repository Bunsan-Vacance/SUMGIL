# Kafka 로컬 구성 (S15P21A104-74 PoC)

수집기가 외부 API에서 떠온 값을 컨슈머(Redis 반영 · AI Spark)로 넘기는 버퍼다.
이 문서는 **브로커를 띄우고 송수신이 되는지 확인하는 방법**까지만 다룬다. 수집기·프로듀서 본 코드는 2주차 티켓이다.

| 항목 | 값 |
| --- | --- |
| 이미지 | `apache/kafka:4.2.1` (ZooKeeper 없음 — KRaft 단독) |
| 컨테이너 | `sumgil-kafka` |
| 호스트 접속 | `localhost:9092` |
| 컨테이너 간 접속 | `kafka:19092` (호스트에 공개 안 함) |
| 볼륨 | `sumgil_kafka_data` |
| 라이브러리 | `spring-kafka` 4.1.1 · `kafka-clients` 4.2.1 (Spring Boot 4.1.1 BOM) |

---

## 1. 기동

```bash
# 저장소 루트에서
docker compose -f Infra/docker/docker-compose.yml up -d kafka

# 준비될 때까지 (healthcheck 가 붙어 있다)
docker compose -f Infra/docker/docker-compose.yml ps kafka
```

`STATUS` 가 `healthy` 가 되면 쓸 수 있다. 처음 기동은 20~30초 걸린다.

---

## 2. 리스너가 두 개인 이유

Kafka 는 클라이언트가 처음 접속하면 **"앞으로 여기로 붙어라"** 하고 주소를 하나 되돌려준다(`advertised.listeners`).
그 주소가 접속한 쪽에서 닿지 않는 주소면, 첫 연결은 성공했는데 그 다음부터 조용히 타임아웃 난다.

컨테이너 안과 밖은 닿는 주소가 다르다.

```
┌─ docker network ──────────────────┐
│  [be] [spark]  ──▶ kafka:19092    │   INTERNAL
│                      ▲            │
│                 [sumgil-kafka]    │
└──────────────────────┼────────────┘
                       │
   호스트 JVM ─────────┘  localhost:9092    EXTERNAL
   (IDE · gradlew · 수집기)
```

그래서 리스너를 두 개 두고 각각 다른 주소를 광고한다.

```yaml
KAFKA_LISTENERS:            INTERNAL://0.0.0.0:19092,EXTERNAL://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
KAFKA_ADVERTISED_LISTENERS: INTERNAL://kafka:19092,EXTERNAL://localhost:9092
```

**한 이름으로 합치면 한쪽이 깨진다.** `kafka:19092` 하나만 광고하면 호스트에서 `kafka` 라는 이름을 못 찾고,
`localhost:9092` 하나만 광고하면 다른 컨테이너가 자기 자신의 localhost 를 보게 된다.

---

## 3. 송수신 확인

### 3-1. 컨테이너 안에서 (브로커가 살아 있는지)

```bash
# Git Bash(Windows)는 /opt/... 를 윈도우 경로로 바꿔버려 다음 오류가 난다:
#   exec: "C:/Program Files/Git/opt/kafka/bin/kafka-topics.sh": no such file or directory
# 이 변수를 먼저 준다. PowerShell·WSL·macOS 는 필요 없다.
export MSYS_NO_PATHCONV=1

C=sumgil-kafka
K=/opt/kafka/bin

# 토픽 생성
docker exec $C $K/kafka-topics.sh --bootstrap-server localhost:9092 \
  --create --topic subway.arrival --partitions 1 --replication-factor 1

# 목록 확인
docker exec $C $K/kafka-topics.sh --bootstrap-server localhost:9092 --list

# 1건 넣기
echo '{"source":"subway","entity_id":"150","payload":{"arrival_sec":120}}' \
  | docker exec -i $C $K/kafka-console-producer.sh \
      --bootstrap-server localhost:9092 --topic subway.arrival

# 처음부터 꺼내기 (안 끝나므로 --timeout-ms 로 자른다)
docker exec $C $K/kafka-console-consumer.sh --bootstrap-server localhost:9092 \
  --topic subway.arrival --from-beginning --timeout-ms 5000
```

재시작 후에도 남는지(볼륨 확인):

```bash
docker compose -f Infra/docker/docker-compose.yml restart kafka
# healthy 대기 후 위 console-consumer 를 다시 실행 → 같은 1건이 나와야 한다
```

### 3-2. 호스트에서 (수집기가 실제로 쓸 경로)

3-1 은 브로커가 살아 있다는 것만 말해 준다. 우리 수집기는 컨테이너 **밖**에서 붙으므로
외부 리스너가 맞는지는 따로 봐야 한다. `KafkaRoundTripIT` 가 그걸 한다.

```bash
cd BE
KAFKA_BOOTSTRAP_SERVERS=localhost:9092 ./gradlew test --tests '*KafkaRoundTripIT*'
```

환경변수가 없으면 **건너뛴다**(`@EnabledIfEnvironmentVariable`). CI(`be-test`)에는 Kafka 서비스가 없어서,
이 PoC 때문에 파이프라인을 바꾸지 않으려고 그렇게 뒀다. 브로커를 띄우고 위 명령을 줄 때만 실제로 돈다.

---

## 4. 확정된 설계 (아키텍처 설계서 · 2026-09-08 AI팀 합의)

본 구현은 2주차 수집기 티켓에서 한다. 여기 적는 건 PoC 가 그 모양에 맞는지 확인하기 위한 요약이다.

| 항목 | 값 |
| --- | --- |
| 토픽 | 소스별 1개 — `subway.arrival` · `bike.stock` · `bus.position` |
| 파티션 | **1** (순서 보장이 재고·도착 반영에 필요) |
| 이벤트 | `{event_id, source, entity_id, source_generated_at, ingested_at, payload}` |
| `event_id` | `source + entity_id + source_generated_at + payload_hash` (NFR-STREAM-006) |
| 멱등 반영 | 컨슈머가 Redis 에 쓸 때 **기존 값의 `source_generated_at` 보다 새 이벤트가 최신일 때만** 덮어쓴다 (NFR-STREAM-004) |
| 컨슈머 그룹 | BE 반영용·AI Spark 용을 **따로** 둔다. 같은 이벤트를 양쪽이 각자 읽는다 |

`bikeList` 는 생성시각 필드가 없어 `ingested_at`(수신시각)이 신선도 기준이다 — `docs/external/api-survey.md` 2절.

---

## 5. 알아둘 것

- **Kafka 4.x 에는 ZooKeeper 가 없다.** 웹의 ZooKeeper 기반 compose 예제를 섞으면 뜨지 않는다.
- **토픽 이름의 `.` 은 경고가 뜬다.** `subway.arrival` 처럼 `.` 을 쓰면 메트릭 이름에서 `_` 와 충돌할 수 있다는 경고가 나온다. 둘을 섞지만 않으면 되고, 우리 토픽은 전부 `.` 만 쓴다.
- **`CLUSTER_ID` 는 고정값이다.** 볼륨에 남은 메타데이터와 어긋나면 기동이 실패한다. 초기화하려면 볼륨을 지운다:
  `docker compose -f Infra/docker/docker-compose.yml down -v` (postgres·redis 데이터도 같이 날아가니 주의).
- **복제본은 전부 1.** 브로커가 1대라 기본값(3)이면 내부 토픽(`__consumer_offsets`) 생성이 막혀 조용히 멈춘다.
- **힙을 512m 로 낮췄다.** 기본 1GB 인데 개발 PC 에서 Postgres·Redis 와 같이 뜬다.
- **9092 는 로컬 전용이다.** EC2 에서는 `ports:` 로 공개하지 않는다 — Docker 가 UFW 를 우회하므로 열면 그대로 인터넷에 노출된다. 배포 시 5432·6379 와 함께 정리한다(`Infra/README.md`).
- `spring-kafka` 는 지금 **`testImplementation`** 이다. API 서버 컨텍스트에 Kafka 빈이 생기지 않게 한 것이고, 수집기가 생기면 `implementation` 으로 옮긴다.

---

## 6. 다음 단계

1. 수집기 v1 — 60초/120초 주기로 외부 API 호출 → `producer.send()` (2주차)
2. 컨슈머 — Kafka → Redis 반영, `source_generated_at` 비교로 멱등 (2주차)
3. 토픽·스키마·보존기간·컨슈머 그룹 정식 인터페이스 문서 → AI·B 리뷰 (2026-09-08 약속)
4. EC2 포트 정책 정리 (9092 미공개 확인)
