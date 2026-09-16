package com.ssafy.s15p21a104.consume;

import com.ssafy.s15p21a104.collect.OperatingWindow;
import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.collect.event.CollectEventJson;
import com.ssafy.s15p21a104.collect.publish.EventPublisher;
import com.ssafy.s15p21a104.collect.publish.KafkaEventPublisher;
import com.ssafy.s15p21a104.collect.publish.RedisApplyingPublisher;
import com.ssafy.s15p21a104.global.config.RedisConfig;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.apache.kafka.clients.admin.AdminClient;
import org.apache.kafka.clients.admin.AdminClientConfig;
import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.common.serialization.StringSerializer;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.kafka.core.DefaultKafkaProducerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import tools.jackson.databind.json.JsonMapper;

/**
 * 비교 B — <b>Kafka 경유 vs Redis 직접 쓰기</b> 의 수집기 회차 소요 (S15P21A104-171, perf 규약 원칙 2).
 *
 * <p><b>무엇을 재는가.</b> 수집기가 한 회차를 "내보내는 데" 걸리는 시간이다. 같은 이벤트 목록을 두 {@code EventPublisher}
 * 구현에 똑같이 넣고 잰다 — 외부 API 를 부르지 않으므로 하루 1,000회 예산을 쓰지 않고, 몇 번이든 반복할 수 있다
 * (규약 원칙 3 의 "워밍업 1회 + 5회 이상" 을 실제로 채울 수 있는 이유).
 *
 * <p><b>무엇을 재지 않는가.</b> end-to-end 지연(이벤트가 Redis 에 보이기까지)은 여기서 안 나온다 —
 * Kafka 경로는 컨슈머가 따로 돌아야 완성되기 때문이다. 그쪽은 prod 에서 {@code ingested_at → 레코드 timestamp → written_at}
 * 세 시각을 회차마다 로그로 남겨 며칠치를 모은다 ({@code consumer.md} 4절).
 *
 * <p><b>결과를 어떻게 읽는가.</b> Kafka 경유가 빠르게 나와도 "Kafka 가 빠르다" 가 아니다 — 직접 쓰기는 이 시간 안에
 * Redis 반영까지 끝내지만, Kafka 경유는 브로커에 넘기기만 하고 반영은 컨슈머가 따로 한다. 둘은 일의 양이 다르다.
 * 이 수치의 쓸모는 "수집기가 회차 주기(60초)를 지킬 여유가 있는가" 와 "스위치를 돌려도 수집기가 버티는가" 다.
 *
 * <p>실행:
 * <pre>
 *   PERF=1 PERF_DUMP=.claude/perf/raw/subway-dump-2026-09-16.jsonl \
 *   KAFKA_BOOTSTRAP_SERVERS=localhost:9092 REDIS_HOST=localhost \
 *   ./gradlew test --tests '*PublisherBenchmarkIT' -i
 * </pre>
 */
@EnabledIfEnvironmentVariable(named = "PERF", matches = "1",
        disabledReason = "성능 측정은 평소 빌드에서 돌리지 않는다. PERF=1 로 켠다")
@EnabledIfEnvironmentVariable(named = "KAFKA_BOOTSTRAP_SERVERS", matches = ".+",
        disabledReason = "브로커가 필요하다")
class PublisherBenchmarkIT {

    private static final int WARMUP = 1;
    private static final int RUNS = 5;
    private static final String TOPIC = "perf.kafka-vs-direct";

    private static final String BOOTSTRAP = System.getenv("KAFKA_BOOTSTRAP_SERVERS");
    private static final String REDIS_HOST = System.getenv().getOrDefault("REDIS_HOST", "localhost");
    private static final int REDIS_PORT = Integer.parseInt(System.getenv().getOrDefault("REDIS_PORT", "6379"));

    private final CollectEventJson json = new CollectEventJson(JsonMapper.builder().build());

    @Test
    @DisplayName("같은 회차를 Kafka 경유 / Redis 직접 쓰기로 각각 워밍업 1 + 5회")
    void 비교() throws Exception {
        List<CollectEvent> round = loadOneRound();
        System.out.printf("%n표본: %s 토픽 %d건 (poll_run_at %s)%n",
                round.get(0).source(), round.size(), round.get(0).pollRunAt());

        createTopic();
        LettuceConnectionFactory redisFactory = new LettuceConnectionFactory(REDIS_HOST, REDIS_PORT);
        redisFactory.afterPropertiesSet();
        DefaultKafkaProducerFactory<String, String> producerFactory = producerFactory();
        try {
            RedisTemplate<String, Object> redis = new RedisConfig().redisTemplate(redisFactory);
            RedisWriter writer = new RedisTemplateWriter(redis);
            Clock clock = Clock.systemUTC();

            EventPublisher kafka = new KafkaEventPublisher(
                    new KafkaTemplate<>(producerFactory), json, Duration.ofSeconds(30));
            EventPublisher direct = new RedisApplyingPublisher(List.of(
                    new BikeStockApplier(writer, clock),
                    new SubwayArrivalApplier(writer, StatnIdMap.fromClasspath(),
                            OperatingWindow.parse("00:00-24:00"), clock)));

            LatencyStats kafkaStats = measure("Kafka 경유", kafka, TOPIC, round);
            LatencyStats directStats = measure("Redis 직접", direct, round.get(0).source(), round);

            System.out.printf("%n| 조건 | 스위치 | min | median | p95 | max |%n");
            System.out.printf("| --- | --- | --- | --- | --- | --- |%n");
            System.out.printf("| Kafka 경유 (브로커에 넘기기까지) | collect.publisher=kafka | %d | %d | %d | %d |%n",
                    kafkaStats.min(), kafkaStats.median(), kafkaStats.p95(), kafkaStats.max());
            System.out.printf("| Redis 직접 (반영까지 끝) | collect.publisher=redis | %d | %d | %d | %d |%n",
                    directStats.min(), directStats.median(), directStats.p95(), directStats.max());
            System.out.printf("%n단위 ms · 워밍업 %d회 + 측정 %d회 · 같은 회차 %d건%n", WARMUP, RUNS, round.size());
        } finally {
            producerFactory.destroy();
            redisFactory.destroy();
        }
    }

    private LatencyStats measure(String label, EventPublisher publisher, String topic, List<CollectEvent> round) {
        for (int i = 0; i < WARMUP; i++) {
            publisher.publish(topic, round);
        }
        List<Long> millis = new ArrayList<>(RUNS);
        for (int i = 0; i < RUNS; i++) {
            long started = System.nanoTime();
            publisher.publish(topic, round);
            millis.add((System.nanoTime() - started) / 1_000_000);
        }
        LatencyStats stats = LatencyStats.of(millis);
        System.out.printf("  %-12s %s%n", label, stats);
        return stats;
    }

    /** 덤프에서 가장 건수가 많은 회차 하나. 잘린 회차를 쓰면 회차마다 건수가 달라져 비교가 흔들린다. */
    private List<CollectEvent> loadOneRound() throws Exception {
        String path = System.getenv("PERF_DUMP");
        if (path == null || path.isBlank()) {
            throw new IllegalStateException("PERF_DUMP 에 덤프 경로가 필요하다 (consumer.md 1절의 덤프 명령 참고)");
        }
        Map<String, List<CollectEvent>> byRun = new LinkedHashMap<>();
        for (String line : Files.readAllLines(Path.of(path), StandardCharsets.UTF_8)) {
            if (line.isBlank()) {
                continue;
            }
            CollectEvent event = json.read(line);
            byRun.computeIfAbsent(String.valueOf(event.pollRunAt()), k -> new ArrayList<>()).add(event);
        }
        return byRun.values().stream().max((a, b) -> Integer.compare(a.size(), b.size())).orElseThrow();
    }

    private static void createTopic() throws Exception {
        try (AdminClient admin = AdminClient.create(Map.of(AdminClientConfig.BOOTSTRAP_SERVERS_CONFIG, BOOTSTRAP))) {
            if (!admin.listTopics().names().get().contains(TOPIC)) {
                admin.createTopics(List.of(new NewTopic(TOPIC, 1, (short) 1))).all().get();
            }
        }
    }

    /** 수집기와 같은 프로듀서 설정 — 여기가 다르면 비교가 성립하지 않는다 (CollectConfig 참고). */
    private static DefaultKafkaProducerFactory<String, String> producerFactory() {
        Map<String, Object> config = new HashMap<>();
        config.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, BOOTSTRAP);
        config.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
        config.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
        config.put(ProducerConfig.ACKS_CONFIG, "all");
        config.put(ProducerConfig.ENABLE_IDEMPOTENCE_CONFIG, true);
        config.put(ProducerConfig.LINGER_MS_CONFIG, 20);
        config.put(ProducerConfig.BATCH_SIZE_CONFIG, 64 * 1024);
        config.put(ProducerConfig.COMPRESSION_TYPE_CONFIG, "lz4");
        config.put(ProducerConfig.MAX_BLOCK_MS_CONFIG, (int) Duration.ofSeconds(10).toMillis());
        return new DefaultKafkaProducerFactory<>(config);
    }
}
