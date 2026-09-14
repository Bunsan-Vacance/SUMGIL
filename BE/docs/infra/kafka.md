# Kafka — 브로커 구성 · 토픽 · 이벤트 계약

수집기가 외부 API에서 떠온 값을 컨슈머(Redis 반영 · AI Spark)로 넘기는 버퍼다.
1~3절은 **로컬 브로커를 띄우고 송수신을 확인하는 법**(S15P21A104-74 PoC), 4절은 **토픽·보관 정책**(168),
5절은 **이벤트 계약**(169 — AI·B 컨슈머가 보는 정본)이다. 수집기 자체를 돌리는 법은 [collector.md](collector.md).

| 항목 | 로컬 (compose) | prod (k3s, `Infra/k8s/prod/kafka.yaml`) |
| --- | --- | --- |
| 이미지 | `apache/kafka:4.2.1` (ZooKeeper 없음 — KRaft 단독) | 같음 |
| 접속 | 호스트 `localhost:9092` · 컨테이너 간 `kafka:19092` | 클러스터 안 `kafka:9092` (ClusterIP 전용) |
| 볼륨 | `sumgil_kafka_data` | local-path PVC **5Gi** |
| 라이브러리 | `spring-kafka` 4.1.1 · `kafka-clients` 4.2.1 (Spring Boot 4.1.1 BOM) | |

---

## 1. 기동

```bash
# 저장소 루트에서
docker compose -f Infra/docker/docker-compose.yml up -d --wait kafka
docker compose -f Infra/docker/docker-compose.yml ps kafka     # STATUS healthy 면 쓸 수 있다 (처음 20~30초)
```

---

## 2. 리스너가 두 개인 이유

Kafka 는 클라이언트가 처음 접속하면 **"앞으로 여기로 붙어라"** 하고 주소를 하나 되돌려준다(`advertised.listeners`).
그 주소가 접속한 쪽에서 닿지 않는 주소면, 첫 연결은 성공했는데 그 다음부터 조용히 타임아웃 난다.

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

```yaml
KAFKA_LISTENERS:            INTERNAL://0.0.0.0:19092,EXTERNAL://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
KAFKA_ADVERTISED_LISTENERS: INTERNAL://kafka:19092,EXTERNAL://localhost:9092
```

**한 이름으로 합치면 한쪽이 깨진다.** prod 는 파드끼리만 붙으므로 `PLAINTEXT://kafka:9092` 하나다 — 노드 호스트에서 프로듀서를 돌릴 일이 생기면 그때 NodePort 를 연다.

---

## 3. 송수신 확인

### 3-1. 컨테이너 안에서 (브로커가 살아 있는지)

```bash
# Git Bash(Windows)는 /opt/... 를 윈도우 경로로 바꿔버린다. PowerShell·WSL·macOS 는 필요 없다.
export MSYS_NO_PATHCONV=1
C=sumgil-kafka; K=/opt/kafka/bin

docker exec $C $K/kafka-topics.sh --bootstrap-server localhost:9092 --list
echo '{"source":"subway","entity_id":"150","payload":{"arrival_sec":120}}' \
  | docker exec -i $C $K/kafka-console-producer.sh --bootstrap-server localhost:9092 --topic subway.arrival
docker exec $C $K/kafka-console-consumer.sh --bootstrap-server localhost:9092 \
  --topic subway.arrival --from-beginning --timeout-ms 5000
```

### 3-2. 호스트에서 (수집기가 실제로 쓸 경로)

3-1 은 브로커 생존만 말해 준다. 외부 리스너가 맞는지는 호스트 JVM 에서 붙어 봐야 한다.

```bash
cd BE
KAFKA_BOOTSTRAP_SERVERS=localhost:9092 ./gradlew test --tests '*KafkaRoundTripIT*'      # PoC 왕복 1건
KAFKA_BOOTSTRAP_SERVERS=localhost:9092 ./gradlew test --tests '*CollectorKafkaIT*'      # 토픽 설정 + 계약 JSON 왕복
```

환경변수가 없으면 둘 다 **건너뛴다**(`@EnabledIfEnvironmentVariable`). CI(`be-test`)에는 Kafka 서비스가 없다.

### 3-3. 수집기로 한 회차 넣어 보기

```bash
SPRING_PROFILES_ACTIVE=local,collect ./gradlew bootRun --args='--collect.run-once=true --collect.bike.enabled=false --collect.weather.enabled=false'
docker exec $C $K/kafka-get-offsets.sh --bootstrap-server localhost:9092 --topic subway.arrival   # 오프셋이 약 3,000 늘어야 한다
```

---

## 4. 토픽과 보관 정책 (S15P21A104-168)

| 토픽 | 파티션 | 복제본 | `retention.ms` | `retention.bytes` | `segment.ms` | `segment.bytes` |
| --- | --- | --- | --- | --- | --- | --- |
| `subway.arrival` | 1 | 1 | 48h | 1.5 GiB | 6h | 128 MiB |
| `bike.stock` | 1 | 1 | 48h | 1 GiB | 6h | 128 MiB |
| `weather.nowcast` | 1 | 1 | 48h | 64 MiB | 6h | 128 MiB |

**어떻게 만드나.** 수집기(`collect` 프로파일)가 기동할 때 `KafkaAdmin` 이 위 정의(`CollectTopics.java`, 값은
`application-collect.yml` 의 `collect.topics.*`·`collect.<소스>.retention-bytes`)로 **없으면 만들고 있으면 설정을 맞춘다**(`modifyTopicConfigs`).
로컬 compose 와 prod 에 같은 코드가 같은 값을 적용한다. 수집기를 올리기 전에 prod 에 토픽만 먼저 두고 싶거나 값을 눈으로 볼 때는
CLI 스크립트를 쓴다 — 두 곳의 값은 같아야 한다.

```bash
bash BE/scripts/kafka/topics.sh          # 로컬 compose — 만들고/맞추고 describe
bash BE/scripts/kafka/topics.sh describe # 확인만

# prod — 노드에 올려서 실행한다. 로컬 PC 에는 kubeconfig 가 없고, k8s API(6443)는 ufw 가 막고 VPN 평면에 있다.
# 노드 안에서는 k3s 가 kubeconfig 를 이미 들고 있어 sudo kubectl 이 바로 된다 (접속은 팀 pem, Infra/README.md).
scp -i <팀 pem> BE/scripts/kafka/topics.sh ubuntu@j15a104.p.ssafy.io:/tmp/topics.sh
ssh -i <팀 pem> ubuntu@j15a104.p.ssafy.io \
  'KAFKA_EXEC="sudo kubectl exec -n prod sts/kafka --" bash /tmp/topics.sh; rm -f /tmp/topics.sh'
```

**적용 결과 (2026-09-14).** 로컬·prod 양쪽에서 생성 경로를 실행해 값이 같은 것을 확인했다.

```
생성       subway.arrival
cleanup.policy=delete retention.bytes=1610612736 retention.ms=172800000 segment.bytes=134217728 segment.ms=21600000
생성       bike.stock
cleanup.policy=delete retention.bytes=1073741824 retention.ms=172800000 segment.bytes=134217728 segment.ms=21600000
생성       weather.nowcast
cleanup.policy=delete retention.bytes=67108864  retention.ms=172800000 segment.bytes=134217728 segment.ms=21600000
```

세 토픽 모두 `PartitionCount: 1` · `ReplicationFactor: 1`. 재실행하면 "생성" 대신 "설정 맞춤"으로 빠지고 결과는 같다(멱등).
`kafka-configs --describe` 출력의 `synonyms={...}` 에는 브로커 기본값(`retention.bytes=-1` 등)이 섞여 있으니 그대로 읽지 않는다 — 스크립트가 걸러서 보여준다.

**왜 이 값인가.**

- **파티션 1** — 순서 보장이 재고·도착 반영에 필요하다(설계서). 복제본 1은 브로커가 1대라서.
- **48시간** — prod 볼륨이 5Gi 다. 기본 보관(7일)이면 넘친다. 컨슈머(be-redis·ai-spark)가 하루 넘게 죽어 있어도 따라잡을 여유는 있다.
- **`retention.bytes`** — 시간 보관이 어긋나도 디스크가 넘치지 않게 하는 둘째 방어선. 파티션 1이라 토픽 상한과 같다. 셋 합쳐 2.56 GiB, 내부 토픽(`__consumer_offsets`)까지 5Gi 안.
- **`segment.ms`·`segment.bytes`** — Kafka 는 **닫힌 세그먼트만** 지운다. 기본값(7일·1GiB)이면 활성 세그먼트가 48시간 안에 안 닫혀 삭제가 일어나지 않는다. 6시간·128MiB 로 잘라 늦어도 54시간 안에 지워진다.

**용량 계산.** 실측(2026-09-14, lz4 압축 프로듀서): 지하철 한 회차 3,002 이벤트가 디스크 730KB — 이벤트당 약 240B.

| 토픽 | 이벤트/회차 | 회차/일 (기본 창) | 이벤트/일 | 디스크/일 (약 240B, lz4) | 48h |
| --- | --- | --- | --- | --- | --- |
| `subway.arrival` | ~3,000 | 330 | ~1.0M | ~240 MB | **~480 MB** (상한 1.5 GiB) |
| `bike.stock` | 2,732 | 330 | ~0.9M | ~150 MB (행이 짧다, 추정) | **~300 MB** (상한 1 GiB) |
| `weather.nowcast` | ~15 | 24 | 360 | 무시 | 상한 64 MiB |

주기·창을 기본값보다 늘려도(예: 갤러리 승인 후 하루 종일) 지하철 1,440회차 × 730KB ≈ 1 GB/일이라 48h 는 상한(1.5 GiB)에 걸려 잘린다 → 그때는 `retention-bytes` 를 함께 올린다.

---

## 5. 이벤트 계약 (S15P21A104-169)

2026-09-08 AI팀 합의(토픽·스키마·멱등)에 `weather.nowcast` 토픽과 `poll_run_at` 필드를 더한 것이다(2026-09-14). **AI 컨슈머가 보는 정본.**

| 항목 | 값 |
| --- | --- |
| 토픽 | 소스별 1개 — `subway.arrival`(60초) · `bike.stock`(120초) · `weather.nowcast`(매시). `bus.position` 은 MVP 제외(api-survey 4절 결정 6) |
| 레코드 | 키 = `entity_id` (문자열), 값 = 아래 JSON (UTF-8 문자열). 헤더 없음 |
| 컨슈머 그룹 | BE 반영용 **`be-redis`** · AI Spark 용 **`ai-spark`** — 따로 둔다. 같은 이벤트를 양쪽이 각자 읽는다 |
| 보관 | 48시간 (4절) |
| 멱등 반영 (NFR-STREAM-004) | 컨슈머가 Redis 에 쓸 때 **기존 값의 `source_generated_at` 보다 새 이벤트가 최신일 때만** 덮어쓴다. 따릉이는 `source_generated_at` 이 없으므로 `ingested_at` 으로 비교 |
| 중복 | 같은 행이 두 번 올 수 있다(지하철 페이지 경계). `event_id` 가 같으므로 최근 본 `event_id` 로 걸러낸다 |

```json
{
  "event_id":            "784932211c04…8dc1",              // SHA-256(source|entity_id|source_generated_at|payload_hash), 16진수 64자
  "source":              "subway.arrival",                 // 토픽 이름과 같다
  "entity_id":           "1009000937",                     // 지하철 statnId · 따릉이 stationId(ST-xxx) · 날씨 nx:ny:category
  "source_generated_at": "2026-09-14T11:46:06+09:00",      // 원천이 밝힌 생성 시각. 따릉이는 null
  "ingested_at":         "2026-09-14T11:50:21.461+09:00",  // 우리가 응답을 받은 시각
  "poll_run_at":         "2026-09-14T11:50:21+09:00",      // 회차 시각(초). 같은 회차의 이벤트는 값이 같다 → 회차 스냅샷으로 묶는 키
  "payload":             { "...": "API 응답 행 원본 그대로. 숫자도 문자열로 온 그대로" }
}
```

- 시각은 전부 ISO-8601 + 오프셋(`+09:00`, KST). `payload_hash` 는 payload 를 키 정렬한 정규형 JSON 의 SHA-256.
- `payload` 는 손대지 않는다 — 뒤에서 쓸 필드를 우리가 미리 버리지 않는다. 지하철 31개 필드(`api-survey.md` 2절), 따릉이 7개, 날씨는 API허브 item 그대로.
- 지하철 `statnId` 와 우리 `station.station_id`(서울 역번호)는 체계가 다르다. 대응표는 Redis 반영 컨슈머(171)가 갖는다.
- 회차당 건수: 지하철 약 3,000(첨두 3,000+), 따릉이 2,732, 날씨 약 15. `poll_run_at` 으로 묶으면 그 회차의 전체 스냅샷이다.

---

## 6. 알아둘 것

- **Kafka 4.x 에는 ZooKeeper 가 없다.** 웹의 ZooKeeper 기반 compose 예제를 섞으면 뜨지 않는다.
- **토픽 이름의 `.` 은 경고가 뜬다.** 메트릭 이름에서 `_` 와 충돌할 수 있다는 경고다. 둘을 섞지만 않으면 되고, 우리 토픽은 전부 `.` 만 쓴다.
- **`CLUSTER_ID` 는 고정값이다.** 볼륨에 남은 메타데이터와 어긋나면 기동이 실패한다. 초기화: `docker compose -f Infra/docker/docker-compose.yml down -v` (postgres·redis 데이터도 같이 날아간다).
- **복제본은 전부 1.** 브로커가 1대라 기본값(3)이면 내부 토픽(`__consumer_offsets`) 생성이 막혀 조용히 멈춘다.
- **힙을 512m 로 낮췄다.** 개발 PC 에서 Postgres·Redis 와 같이 뜬다. prod 매니페스트도 같다.
- **9092 는 로컬 전용이다.** prod 는 ClusterIP 만 — 노드 호스트에도 공개하지 않는다.
- **`spring-kafka` 는 `implementation` 이지만 자동 구성은 없다.** 스타터(`spring-boot-starter-kafka`)가 아니라 `spring-kafka` 만 올려서 `KafkaAutoConfiguration` 이 붙지 않는다. Kafka 빈은 `CollectConfig`(collect 프로파일)에서만 만들어지고 API 서버 컨텍스트에는 없다 — `KafkaBeansAbsentTest` 가 못 박는다 (`BE/README.md` 9절).
- **Git Bash 는 `/opt/...` 를 윈도우 경로로 바꾼다.** `export MSYS_NO_PATHCONV=1`.

---

## 7. 다음 단계

1. ~~수집기 v1~~ — 완료 (169, [collector.md](collector.md)). prod 배포는 173.
2. **컨슈머 v1 (171)** — `be-redis` 그룹, Kafka → Redis, `source_generated_at`/`ingested_at` 비교로 멱등, TTL 90초. 지하철 도착 Redis 키를 정해 A 파트에 통보.
3. ~~prod 토픽~~ — 완료 (2026-09-14, 4절 "적용 결과"). 수집기 파드가 올라가면 기동 시 같은 값으로 다시 맞춘다. 지금은 **토픽만 있고 프로듀서·컨슈머가 없어 비어 있다.**
4. AI 컨슈머(`ai-spark`)가 5절 계약으로 붙는다 — `Desktop/ai-part-request-2026-09-14.md` 부탁 2.
