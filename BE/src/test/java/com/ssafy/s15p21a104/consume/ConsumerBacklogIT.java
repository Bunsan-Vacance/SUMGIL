package com.ssafy.s15p21a104.consume;

import com.ssafy.s15p21a104.collect.OperatingWindow;
import com.ssafy.s15p21a104.collect.event.CollectEventJson;
import com.ssafy.s15p21a104.global.config.RedisConfig;
import java.time.Clock;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.apache.kafka.clients.consumer.Consumer;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.common.TopicPartition;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.kafka.core.DefaultKafkaConsumerFactory;
import tools.jackson.databind.json.JsonMapper;

/**
 * 백로그 따라잡기 — 밀린 이벤트를 컨슈머가 얼마나 빨리 소화하는가 (S15P21A104-171).
 *
 * <p>Kafka 를 쓰는 값어치 중 하나가 "컨슈머가 죽어 있어도 보관 48시간치를 나중에 따라잡는다" 인데,
 * 그게 몇 분 걸리는 일인지 알아야 장애 때 판단이 선다. 여기서 재는 것은 <b>우리 컨슈머의 처리 속도</b>다 —
 * 실부하가 초당 약 50건(60초에 3,000건)이라 Kafka 는 병목이 아니고, 막히면 역직렬화·멱등 비교·Redis 쓰기 쪽이다.
 *
 * <p>먼저 백로그를 쌓아 두고 실행한다 (외부 API 호출 0회 — 덤프 재생):
 * <pre>
 *   node BE/scripts/kafka/replay.mjs --dump .claude/perf/raw/subway-dump-2026-09-16.jsonl --times 17 --round \
 *     | docker exec -i sumgil-kafka /opt/kafka/bin/kafka-console-producer.sh \
 *         --bootstrap-server localhost:9092 --topic perf.backlog \
 *         --property parse.key=true --property key.separator='\t'
 *
 *   PERF=1 KAFKA_BOOTSTRAP_SERVERS=localhost:9092 REDIS_HOST=localhost \
 *   ./gradlew test --tests '*ConsumerBacklogIT' -i
 * </pre>
 *
 * <p><b>로컬 compose 에만 쓴다.</b> prod 토픽에 재생분을 넣으면 가짜 재고·도착이 실제 Redis 에 들어가고
 * AI 의 {@code ai-spark} 컨슈머도 그것을 먹는다.
 */
@EnabledIfEnvironmentVariable(named = "PERF", matches = "1",
        disabledReason = "성능 측정은 평소 빌드에서 돌리지 않는다. PERF=1 로 켠다")
@EnabledIfEnvironmentVariable(named = "KAFKA_BOOTSTRAP_SERVERS", matches = ".+",
        disabledReason = "브로커가 필요하다")
class ConsumerBacklogIT {

    private static final String BOOTSTRAP = System.getenv("KAFKA_BOOTSTRAP_SERVERS");
    private static final String TOPIC = System.getenv().getOrDefault("PERF_TOPIC", "perf.backlog");
    private static final String REDIS_HOST = System.getenv().getOrDefault("REDIS_HOST", "localhost");
    private static final int REDIS_PORT = Integer.parseInt(System.getenv().getOrDefault("REDIS_PORT", "6379"));
    /** 운영 설정과 같은 값 (application-consume.yml) — 여기가 다르면 측정이 운영을 대표하지 못한다. */
    private static final int MAX_POLL_RECORDS = 500;

    @Test
    @DisplayName("밀린 백로그를 처음부터 끝까지 소화하는 데 걸리는 시간")
    void 백로그_따라잡기() {
        LettuceConnectionFactory redisFactory = new LettuceConnectionFactory(REDIS_HOST, REDIS_PORT);
        redisFactory.afterPropertiesSet();
        try {
            RedisTemplate<String, Object> redis = new RedisConfig().redisTemplate(redisFactory);
            RedisWriter writer = new RedisTemplateWriter(redis);
            Clock clock = Clock.systemUTC();
            CollectEventJson json = new CollectEventJson(JsonMapper.builder().build());

            BatchDispatcher dispatcher = new BatchDispatcher(List.of(
                    new BikeStockApplier(writer, clock),
                    new SubwayArrivalApplier(writer, StatnIdMap.fromClasspath(),
                            OperatingWindow.parse("00:00-24:00"), clock)),
                    json, clock);

            TopicPartition partition = new TopicPartition(TOPIC, 0);
            try (Consumer<String, String> consumer = consumer()) {
                consumer.assign(List.of(partition));
                long end = consumer.endOffsets(List.of(partition)).get(partition);
                consumer.seekToBeginning(List.of(partition));
                long begin = consumer.position(partition);
                long backlog = end - begin;
                if (backlog <= 0) {
                    throw new IllegalStateException(
                            "%s 에 백로그가 없다 — 위 주석의 replay 명령으로 먼저 쌓는다".formatted(TOPIC));
                }
                System.out.printf("%n백로그 %,d건 (오프셋 %d → %d) · max.poll.records=%d%n",
                        backlog, begin, end, MAX_POLL_RECORDS);

                List<Long> batchMillis = new ArrayList<>();
                List<Long> consumeSpans = new ArrayList<>();
                long consumed = 0;
                int written = 0;
                int ignored = 0;
                int batches = 0;
                long started = System.nanoTime();

                while (consumed < backlog) {
                    var records = consumer.poll(Duration.ofSeconds(5));
                    if (records.isEmpty()) {
                        break;
                    }
                    List<RawRecord> raw = new ArrayList<>(records.count());
                    for (ConsumerRecord<String, String> record : records.records(partition)) {
                        raw.add(new RawRecord(record.topic(), record.value(), record.timestamp()));
                    }
                    long batchStart = System.nanoTime();
                    DispatchResult result = dispatcher.dispatch(raw);
                    batchMillis.add((System.nanoTime() - batchStart) / 1_000_000);
                    consumeSpans.add(result.consume().median());
                    consumed += raw.size();
                    written += result.applied().written();
                    ignored += result.ignored();
                    batches++;
                }

                long elapsedMs = (System.nanoTime() - started) / 1_000_000;

                // 반영기는 Kafka 토픽 이름으로 고른다. 토픽 이름이 subway.arrival·bike.stock 이 아니면 전부 무시되고
                // 루프 오버헤드만 재게 된다 — 한 번 이렇게 잰 적이 있어 가드를 둔다.
                if (written == 0) {
                    throw new IllegalStateException(
                            ("%s 에서 %,d건을 읽었지만 Redis 에 하나도 안 썼다 (무시 %,d건). "
                                    + "토픽 이름이 반영기와 맞는지 확인한다 — subway.arrival 또는 bike.stock 이어야 한다")
                                    .formatted(TOPIC, consumed, ignored));
                }
                System.out.printf("소화 %,d건 · 배치 %d개 · Redis 쓰기 %,d회 · 무시 %,d건 · 총 %,d ms → 초당 %,.0f건%n",
                        consumed, batches, written, ignored, elapsedMs, consumed * 1000.0 / Math.max(1, elapsedMs));
                System.out.printf("  배치 처리 시간  %s%n", LatencyStats.of(batchMillis));
                System.out.printf("  배치별 consume 구간 중앙값의 분포  %s%n", LatencyStats.of(consumeSpans));
                System.out.printf("  실부하 대비 여유: 실제는 초당 약 50건(60초에 3,000건)이다%n");
            }
        } finally {
            redisFactory.destroy();
        }
    }

    private static Consumer<String, String> consumer() {
        Map<String, Object> config = new HashMap<>();
        config.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, BOOTSTRAP);
        config.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
        config.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
        config.put(ConsumerConfig.GROUP_ID_CONFIG, "perf-backlog-" + System.nanoTime());
        config.put(ConsumerConfig.MAX_POLL_RECORDS_CONFIG, MAX_POLL_RECORDS);
        config.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, false);
        return new DefaultKafkaConsumerFactory<String, String>(config).createConsumer();
    }
}
