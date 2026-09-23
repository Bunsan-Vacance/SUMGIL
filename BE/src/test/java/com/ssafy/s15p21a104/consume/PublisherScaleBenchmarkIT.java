package com.ssafy.s15p21a104.consume;

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
import java.util.Set;
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
 * 실험 B — <b>부하 분리</b>: 회차가 커질 때 수집기 회차 소요가 어떻게 늘어나는가 (S15P21A104-311).
 *
 * <p><b>무엇을 재는가.</b> 수집기가 한 회차를 내보내는 시간. 같은 이벤트 목록을 두 {@code EventPublisher} 에 넣는다.
 * <ul>
 *   <li>Before — {@code collect.publisher=redis}: 수집기가 대여소마다 Redis 를 읽고(멱등 비교) 쓴다. 다 쓸 때까지 회차가 안 끝난다</li>
 *   <li>After — {@code collect.publisher=kafka}: 브로커 확인({@code acks=all})까지 받으면 끝. 반영은 컨슈머 몫이다</li>
 * </ul>
 *
 * <p><b>왜 따릉이인가.</b> 따릉이 반영기는 이벤트 1건 = Redis 읽기 1 + 쓰기 1 이라 대여소 수가 곧 일의 양이다.
 * 지하철 반영기는 역 단위로 묶어 최신 회차만 쓰므로 이벤트를 부풀려도 쓰기가 역 수(약 600)에 머문다 — 부하 실험이 안 된다.
 *
 * <p><b>규모.</b> prod 덤프의 가장 큰 회차(대여소 2,743곳)를 기준으로, 행을 복제하고 {@code entity_id} 에 접미사를 붙여
 * 가상의 대여소를 만든다 — 1만·3만·10만 곳. "수집 대상이 늘어나는" 상황(노선·정류소 추가)을 흉내 낸다.
 *
 * <p><b>매 측정마다 새 회차.</b> 같은 회차를 반복하면 반영기가 "이미 같은 시각" 이라 쓰기를 건너뛰어 읽기만 잰다
 * (2026-09-16 kafka-vs-direct 측정의 함정). 그래서 측정 i 는 {@code ingested_at} 을 (i+1)×60초 민 복제본을 쓴다.
 *
 * <p><b>읽는 법.</b> Kafka 경유가 빠르다고 "Kafka 가 빠르다" 가 아니다. 같은 쓰기는 컨슈머가 뒤에서 한다 —
 * 이 실험이 보이는 것은 "수집이 쓰기 속도에 묶이는가" 와 "60초 회차 주기를 넘는 지점" 이다.
 *
 * <p>실행 (로컬 compose 에만):
 * <pre>
 *   PERF=1 PERF_BIKE_DUMP=.claude/perf/raw/bike-dump-2026-09-23.jsonl \
 *   KAFKA_BOOTSTRAP_SERVERS=localhost:9092 REDIS_HOST=localhost \
 *   ./gradlew test --tests '*PublisherScaleBenchmarkIT' -i
 * </pre>
 * {@code PERF_SCALES}(기본 {@code 2743,10000,30000,100000}) 로 규모를 바꾼다.
 */
@EnabledIfEnvironmentVariable(named = "PERF", matches = "1",
        disabledReason = "성능 측정은 평소 빌드에서 돌리지 않는다. PERF=1 로 켠다")
@EnabledIfEnvironmentVariable(named = "KAFKA_BOOTSTRAP_SERVERS", matches = ".+",
        disabledReason = "브로커가 필요하다")
class PublisherScaleBenchmarkIT {

    private static final int WARMUP = 1;
    private static final int RUNS = 5;
    private static final String TOPIC = "perf.scale";
    /** 가상 대여소 접미사. 측정 뒤 이 표식이 붙은 Redis 키만 지운다. */
    private static final String SYNTHETIC = "~s";

    private static final String BOOTSTRAP = System.getenv("KAFKA_BOOTSTRAP_SERVERS");
    private static final String REDIS_HOST = System.getenv().getOrDefault("REDIS_HOST", "localhost");
    private static final int REDIS_PORT = Integer.parseInt(System.getenv().getOrDefault("REDIS_PORT", "6379"));

    private final CollectEventJson json = new CollectEventJson(JsonMapper.builder().build());

    @Test
    @DisplayName("대여소 수를 늘려 가며 Kafka 경유 / Redis 직접의 회차 소요를 워밍업 1 + 5회씩")
    void 규모별_비교() throws Exception {
        List<CollectEvent> base = largestRound();
        List<Integer> scales = scales();
        System.out.printf("%n기준 회차: %s %d곳 (poll_run_at %s) · 규모 %s%n",
                base.get(0).source(), base.size(), base.get(0).pollRunAt(), scales);

        createTopic();
        LettuceConnectionFactory redisFactory = new LettuceConnectionFactory(REDIS_HOST, REDIS_PORT);
        redisFactory.afterPropertiesSet();
        DefaultKafkaProducerFactory<String, String> producerFactory = producerFactory();
        RedisTemplate<String, Object> redis = new RedisConfig().redisTemplate(redisFactory);
        try {
            EventPublisher kafka = new KafkaEventPublisher(
                    new KafkaTemplate<>(producerFactory), json, Duration.ofSeconds(120));
            EventPublisher direct = new RedisApplyingPublisher(List.of(
                    new BikeStockApplier(new RedisTemplateWriter(redis), Clock.systemUTC())));

            List<String> rows = new ArrayList<>();
            int generation = 0;
            for (int size : scales) {
                List<CollectEvent> round = inflate(base, size);
                LatencyStats k = measure("Kafka 경유", kafka, TOPIC, round, generation);
                generation += WARMUP + RUNS;
                LatencyStats d = measure("Redis 직접", direct, "bike.stock", round, generation);
                generation += WARMUP + RUNS;
                rows.add("| %,d | %,d | %,d | %,d | %,d | %,d | %,d |".formatted(size,
                        k.median(), k.p95(), perSecond(size, k.median()),
                        d.median(), d.p95(), perSecond(size, d.median())));
            }

            System.out.printf("%n| 대여소 수 | Kafka median | Kafka p95 | Kafka 건/초 | Redis 직접 median | Redis 직접 p95 | Redis 직접 건/초 |%n");
            System.out.printf("| --- | --- | --- | --- | --- | --- | --- |%n");
            rows.forEach(System.out::println);
            System.out.printf("%n단위 ms · 규모마다 조건별 워밍업 %d회 + 측정 %d회 · 측정마다 ingested_at 을 60초 민 새 회차%n",
                    WARMUP, RUNS);
        } finally {
            Set<String> synthetic = redis.keys("bike:stock:*" + SYNTHETIC + "*");
            if (synthetic != null && !synthetic.isEmpty()) {
                redis.delete(synthetic);
                System.out.printf("정리: 가상 대여소 Redis 키 %,d개 삭제%n", synthetic.size());
            }
            producerFactory.destroy();
            redisFactory.destroy();
        }
    }

    /** 워밍업 뒤 측정. 모든 실행이 서로 다른 세대(generation)의 새 회차라 Redis 직접이 매번 실제로 쓴다. */
    private LatencyStats measure(String label, EventPublisher publisher, String topic, List<CollectEvent> round,
                                 int generation) {
        for (int i = 0; i < WARMUP; i++) {
            publisher.publish(topic, shift(round, generation + i));
        }
        List<Long> millis = new ArrayList<>(RUNS);
        for (int i = 0; i < RUNS; i++) {
            List<CollectEvent> fresh = shift(round, generation + WARMUP + i);
            long started = System.nanoTime();
            int published = publisher.publish(topic, fresh);
            millis.add((System.nanoTime() - started) / 1_000_000);
            if (published != fresh.size()) {
                throw new IllegalStateException(label + " 가 " + fresh.size() + "건 중 " + published + "건만 처리했다 — 측정 무효");
            }
        }
        LatencyStats stats = LatencyStats.of(millis);
        System.out.printf("  %,7d곳 %-10s 원본 %s → %s%n", round.size(), label, millis, stats);
        return stats;
    }

    /** 기준 회차를 size 곳으로 늘린다. 원본을 먼저 쓰고, 모자라면 접미사를 붙인 복제본으로 채운다. */
    private static List<CollectEvent> inflate(List<CollectEvent> base, int size) {
        List<CollectEvent> out = new ArrayList<>(size);
        for (int copy = 0; out.size() < size; copy++) {
            for (CollectEvent e : base) {
                if (out.size() == size) {
                    break;
                }
                String id = copy == 0 ? e.entityId() : e.entityId() + SYNTHETIC + copy;
                out.add(new CollectEvent(e.eventId() + (copy == 0 ? "" : SYNTHETIC + copy), e.source(), id,
                        e.sourceGeneratedAt(), e.ingestedAt(), e.pollRunAt(), e.payload()));
            }
        }
        return out;
    }

    /** 세대 g 의 새 회차 — 시각 둘을 (g+1)×60초 민다. 반영기의 "더 새로울 때만" 규칙을 통과해 매번 쓰게 한다. */
    private static List<CollectEvent> shift(List<CollectEvent> round, int generation) {
        long seconds = (generation + 1L) * 60;
        List<CollectEvent> out = new ArrayList<>(round.size());
        for (CollectEvent e : round) {
            out.add(new CollectEvent(e.eventId() + "#" + generation, e.source(), e.entityId(), e.sourceGeneratedAt(),
                    e.ingestedAt().plusSeconds(seconds), e.pollRunAt().plusSeconds(seconds), e.payload()));
        }
        return out;
    }

    private static long perSecond(int size, long millis) {
        return millis <= 0 ? 0 : Math.round(size * 1000.0 / millis);
    }

    private static List<Integer> scales() {
        String raw = System.getenv().getOrDefault("PERF_SCALES", "2743,10000,30000,100000");
        List<Integer> out = new ArrayList<>();
        for (String part : raw.split(",")) {
            out.add(Integer.parseInt(part.trim()));
        }
        return out;
    }

    /** 덤프에서 대여소 수가 가장 많은 회차 하나. */
    private List<CollectEvent> largestRound() throws Exception {
        String path = System.getenv("PERF_BIKE_DUMP");
        if (path == null || path.isBlank()) {
            throw new IllegalStateException("PERF_BIKE_DUMP 에 bike.stock 덤프 경로가 필요하다 (perf 문서의 덤프 명령 참고)");
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

    /** 수집기와 같은 프로듀서 설정 (CollectConfig · PublisherBenchmarkIT 와 같다). */
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
