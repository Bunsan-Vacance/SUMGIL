package com.ssafy.s15p21a104.consume;

import com.ssafy.s15p21a104.collect.OperatingWindow;
import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.collect.event.CollectEventJson;
import com.ssafy.s15p21a104.global.config.RedisConfig;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicLong;
import org.apache.kafka.clients.admin.AdminClient;
import org.apache.kafka.clients.admin.AdminClientConfig;
import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.clients.consumer.Consumer;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.RedisTemplate;
import tools.jackson.databind.json.JsonMapper;

/**
 * 실험 A(장애 복구)·C(파티션 확장) — 컨슈머가 멈춘 동안 쌓인 이벤트를 비우는 시간 (S15P21A104-311).
 *
 * <p><b>상황.</b> 컨슈머가 N분 멈췄다(배포·재시작·크래시). 수집기는 그동안에도 Kafka 에 계속 쌓는다 — 1분마다 지하철 1회차
 * (약 2,900건)와 따릉이 1회차(2,743곳). 컨슈머가 돌아오면 마지막 커밋 지점부터 다시 읽는다. 여기서는 그 N분치를
 * 미리 쌓아 두고, 실제 반영 코드({@link BatchDispatcher} + 반영기 둘)로 끝까지 비운다.
 *
 * <p><b>유실 0 판정.</b> 소화 건수 = 쌓은 건수, 반영 실패 0, 그리고 따릉이 대여소 전부의 Redis 값이 <b>마지막 회차</b>의
 * {@code ingested_at} 이어야 한다. 중간 회차가 빠지면 최종 값이 앞 회차로 남는다.
 *
 * <p><b>Before 와의 관계.</b> 직접 쓰기에서는 쓰는 쪽이 곧 수집기라, 재배포하는 N분 동안 수집 자체가 멈추고 그 회차는
 * 영영 비어 있다. 여기서 재는 것은 Kafka 가 있을 때 그 N분이 "유실" 이 아니라 "밀린 일" 이 되고, 몇 초 만에 따라잡는가다.
 *
 * <p><b>일부러 재지 않는 것.</b> Redis 자체가 죽는 경우 — 지금 {@code BatchDispatcher} 는 반영 실패를 로그만 남기고
 * 배치를 정상 종료해 오프셋이 커밋된다(원본은 Kafka 에 48시간 남아 수동 재처리는 가능). 발표 한계로 따로 적는다.
 *
 * <p>실행 (로컬 compose 에만 — 로컬 {@code subway.arrival}·{@code bike.stock} 토픽을 지우고 다시 만든다):
 * <pre>
 *   PERF=1 PERF_DUMP=.claude/perf/raw/subway-dump-2026-09-23.jsonl \
 *   PERF_BIKE_DUMP=.claude/perf/raw/bike-dump-2026-09-23.jsonl \
 *   KAFKA_BOOTSTRAP_SERVERS=localhost:9092 REDIS_HOST=localhost \
 *   ./gradlew test --tests '*ConsumerRecoveryScaleIT' -i
 * </pre>
 */
@EnabledIfEnvironmentVariable(named = "PERF", matches = "1",
        disabledReason = "성능 측정은 평소 빌드에서 돌리지 않는다. PERF=1 로 켠다")
@EnabledIfEnvironmentVariable(named = "KAFKA_BOOTSTRAP_SERVERS", matches = ".+",
        disabledReason = "브로커가 필요하다")
class ConsumerRecoveryScaleIT {

    private static final int WARMUP = 1;
    private static final int RUNS = 5;
    /** 운영과 같은 값 (application-consume.yml). */
    private static final int MAX_POLL_RECORDS = 500;
    private static final List<String> TOPICS = List.of("subway.arrival", "bike.stock");

    private static final String BOOTSTRAP = System.getenv("KAFKA_BOOTSTRAP_SERVERS");
    private static final String REDIS_HOST = System.getenv().getOrDefault("REDIS_HOST", "localhost");
    private static final int REDIS_PORT = Integer.parseInt(System.getenv().getOrDefault("REDIS_PORT", "6379"));

    private final CollectEventJson json = new CollectEventJson(JsonMapper.builder().build());

    @Test
    @DisplayName("A: 컨슈머가 N분 멈춘 동안 쌓인 분량을 유실 없이 따라잡는 시간 (파티션 1 · 컨슈머 1 = 운영과 같다)")
    void A_장애_복구() throws Exception {
        List<Integer> minutes = intList("PERF_OUTAGE_MINUTES", "3,10");
        Rounds rounds = loadRounds();
        List<String> rows = new ArrayList<>();
        // 앞선 측정(B 등)이 같은 대여소 키에 더 늦은 시각을 써 뒀을 수 있다 — 충분히 뒤에서 시작해 "더 새로울 때만" 을 통과시킨다
        int generation = 1_000;
        for (int m : minutes) {
            List<Long> millis = new ArrayList<>();
            Drain last = null;
            for (int run = 0; run < WARMUP + RUNS; run++) {
                Drain d = backlogThenDrain(rounds, m, 1, 1, generation);
                generation += m;
                if (run >= WARMUP) {
                    millis.add(d.millis());
                    last = d;
                }
            }
            LatencyStats s = LatencyStats.of(millis);
            System.out.printf("  A %2d분 중단 · %,d건 → 원본 %s → %s · 합류 %,dms%n", m, last.events(), millis, s, last.joinMillis());
            rows.add("| %d분 | %,d | %,d | %,d | %,d | %s |".formatted(m, last.events(), s.median(), s.p95(),
                    Math.round(last.events() * 1000.0 / s.median()), last.lossLine()));
        }
        System.out.printf("%n| 컨슈머 중단 | 쌓인 이벤트 | 따라잡기 median(ms) | p95(ms) | 건/초 | 유실 |%n");
        System.out.printf("| --- | --- | --- | --- | --- | --- |%n");
        rows.forEach(System.out::println);
        System.out.printf("%n파티션 1 · 컨슈머 1 · max.poll.records=%d · 조건별 워밍업 %d + 측정 %d%n",
                MAX_POLL_RECORDS, WARMUP, RUNS);
    }

    @Test
    @DisplayName("C: 같은 백로그를 파티션·컨슈머 1개 vs 3개로 비우는 처리량")
    void C_파티션_확장() throws Exception {
        int minutes = intList("PERF_SCALE_MINUTES", "10").get(0);
        List<Integer> parallel = intList("PERF_PARTITIONS", "1,3");
        Rounds rounds = loadRounds();
        List<String> rows = new ArrayList<>();
        int generation = 10_000;
        for (int p : parallel) {
            List<Long> millis = new ArrayList<>();
            Drain last = null;
            for (int run = 0; run < WARMUP + RUNS; run++) {
                Drain d = backlogThenDrain(rounds, minutes, p, p, generation);
                generation += minutes;
                if (run >= WARMUP) {
                    millis.add(d.millis());
                    last = d;
                }
            }
            LatencyStats s = LatencyStats.of(millis);
            System.out.printf("  C 파티션 %d · 컨슈머 %d · %,d건 → 원본 %s → %s · 합류 %,dms%n", p, p, last.events(), millis, s, last.joinMillis());
            rows.add("| %d | %d | %,d | %,d | %,d | %,d | %s |".formatted(p, p, last.events(), s.median(), s.p95(),
                    Math.round(last.events() * 1000.0 / s.median()), last.lossLine()));
        }
        System.out.printf("%n| 파티션 | 컨슈머 | 이벤트 | 소화 median(ms) | p95(ms) | 건/초 | 유실 |%n");
        System.out.printf("| --- | --- | --- | --- | --- | --- | --- |%n");
        rows.forEach(System.out::println);
        System.out.printf("%n백로그 %d분치 · 컨슈머마다 max.poll.records=%d · 조건별 워밍업 %d + 측정 %d%n",
                minutes, MAX_POLL_RECORDS, WARMUP, RUNS);
    }

    /** 토픽을 새로 만들고 minutes 분치를 쌓은 뒤, consumers 개가 같은 그룹으로 끝까지 비운다. */
    private Drain backlogThenDrain(Rounds rounds, int minutes, int partitions, int consumers, int generation)
            throws Exception {
        LettuceConnectionFactory redisFactory = new LettuceConnectionFactory(REDIS_HOST, REDIS_PORT);
        redisFactory.afterPropertiesSet();
        // 측정끼리 서로 오염되지 않게 비운다 — 앞 측정이 더 늦은 시각을 써 두면 반영기가 "더 새롭지 않다" 며 쓰기를 건너뛰고
        // 읽기만 해 실제보다 빠르게 나온다(2026-09-23 첫 실행에서 실제로 났다). 로컬 Redis 에만 한다.
        clearKeys(new RedisConfig().redisTemplate(redisFactory));
        recreateTopics(partitions);
        long produced = produce(rounds, minutes, generation);
        String group = "perf-recovery-" + UUID.randomUUID();
        AtomicLong consumed = new AtomicLong();
        AtomicLong failed = new AtomicLong();
        AtomicLong firstBatchAt = new AtomicLong();
        ExecutorService pool = Executors.newFixedThreadPool(consumers);
        try {
            RedisTemplate<String, Object> redis = new RedisConfig().redisTemplate(redisFactory);
            long started = System.nanoTime();
            List<Future<?>> workers = new ArrayList<>();
            for (int i = 0; i < consumers; i++) {
                workers.add(pool.submit(() -> {
                    BatchDispatcher dispatcher = new BatchDispatcher(List.of(
                            new BikeStockApplier(new RedisTemplateWriter(redis), Clock.systemUTC()),
                            new SubwayArrivalApplier(new RedisTemplateWriter(redis), StatnIdMap.fromClasspath(),
                                    OperatingWindow.parse("00:00-24:00"), Clock.systemUTC())),
                            json, Clock.systemUTC());
                    try (Consumer<String, String> consumer = consumer(group)) {
                        consumer.subscribe(TOPICS);
                        int idle = 0;
                        while (consumed.get() < produced && idle < 20) {
                            var records = consumer.poll(Duration.ofMillis(500));
                            if (records.isEmpty()) {
                                idle++;
                                continue;
                            }
                            idle = 0;
                            firstBatchAt.compareAndSet(0, System.nanoTime());
                            List<RawRecord> raw = new ArrayList<>(records.count());
                            for (ConsumerRecord<String, String> r : records) {
                                raw.add(new RawRecord(r.topic(), r.value(), r.timestamp()));
                            }
                            DispatchResult result = dispatcher.dispatch(raw);
                            failed.addAndGet(result.failed());
                            consumer.commitSync();
                            consumed.addAndGet(raw.size());
                        }
                    }
                    return null;
                }));
            }
            for (Future<?> w : workers) {
                w.get();
            }
            long end = System.nanoTime();
            // 그룹 합류(리밸런스) 시간은 조건마다 달라 처리량을 흐린다 — 첫 배치를 받은 순간부터 잰다
            long millis = (end - firstBatchAt.get()) / 1_000_000;
            long joinMillis = (firstBatchAt.get() - started) / 1_000_000;

            // 대여소마다 ingested_at 이 다르다(수집이 페이지 3번으로 나뉜다) — 자기 시각 + 마지막 회차만큼 민 값이어야 한다
            long lastShift = (generation + minutes) * 60L;
            long stale = 0;
            for (CollectEvent e : rounds.bike()) {
                OffsetDateTime expected = e.ingestedAt().plusSeconds(lastShift);
                Object stored = redis.opsForValue().get("bike:stock:" + e.entityId());
                OffsetDateTime at = stored instanceof Map<?, ?> m ? Times.parse(m.get("ingested_at")) : null;
                if (at == null || !at.isEqual(expected)) {
                    stale++;
                }
            }
            return new Drain(produced, consumed.get(), failed.get(), stale, rounds.bike().size(), millis, joinMillis);
        } finally {
            pool.shutdownNow();
            redisFactory.destroy();
        }
    }

    /** minutes 회차를 쌓는다. 회차 g 는 (g+1)×60초 민 복제본 — 멱등 규칙을 통과하고 실제 1분 간격과 같다. */
    private long produce(Rounds rounds, int minutes, int generation) {
        long count = 0;
        try (KafkaProducer<String, String> producer = new KafkaProducer<>(producerConfig())) {
            for (int i = 0; i < minutes; i++) {
                long seconds = (generation + i + 1L) * 60;
                for (CollectEvent e : rounds.subway()) {
                    producer.send(new ProducerRecord<>("subway.arrival", e.entityId(), json.write(shift(e, seconds))));
                    count++;
                }
                for (CollectEvent e : rounds.bike()) {
                    producer.send(new ProducerRecord<>("bike.stock", e.entityId(), json.write(shift(e, seconds))));
                    count++;
                }
            }
            producer.flush();
        }
        return count;
    }

    /** 시각 셋과 지하철 payload 의 recptnDt 를 민다 (scripts/kafka/lib/replay.mjs 와 같은 규칙). */
    private static CollectEvent shift(CollectEvent e, long seconds) {
        Map<String, Object> payload = new LinkedHashMap<>(e.payload());
        Object recptn = payload.get("recptnDt");
        if (recptn instanceof String s && s.length() >= 19) {
            payload.put("recptnDt", java.time.LocalDateTime.parse(s.substring(0, 19).replace(' ', 'T'))
                    .plusSeconds(seconds).toString().replace('T', ' '));
        }
        return new CollectEvent(e.eventId() + "#" + seconds, e.source(), e.entityId(),
                e.sourceGeneratedAt() == null ? null : e.sourceGeneratedAt().plusSeconds(seconds),
                e.ingestedAt().plusSeconds(seconds), e.pollRunAt().plusSeconds(seconds), payload);
    }

    private static void clearKeys(RedisTemplate<String, Object> redis) {
        for (String pattern : List.of("bike:stock:*", "subway:arrival:*")) {
            Set<String> keys = redis.keys(pattern);
            if (keys != null && !keys.isEmpty()) {
                redis.delete(keys);
            }
        }
    }

    private static void recreateTopics(int partitions) throws Exception {
        try (AdminClient admin = AdminClient.create(Map.of(AdminClientConfig.BOOTSTRAP_SERVERS_CONFIG, BOOTSTRAP))) {
            Set<String> existing = admin.listTopics().names().get();
            List<String> drop = TOPICS.stream().filter(existing::contains).toList();
            if (!drop.isEmpty()) {
                admin.deleteTopics(drop).all().get();
                for (int i = 0; i < 50 && admin.listTopics().names().get().stream().anyMatch(drop::contains); i++) {
                    Thread.sleep(200);
                }
            }
            List<NewTopic> create = TOPICS.stream().map(t -> new NewTopic(t, partitions, (short) 1)).toList();
            for (int i = 0; ; i++) {
                try {
                    admin.createTopics(create).all().get();
                    return;
                } catch (Exception e) {
                    if (i >= 20) {
                        throw e;
                    }
                    Thread.sleep(300); // 삭제 직후엔 "이미 있음(삭제 중)" 이 잠깐 난다
                }
            }
        }
    }

    private Rounds loadRounds() throws Exception {
        return new Rounds(largestRound("PERF_DUMP"), largestRound("PERF_BIKE_DUMP"));
    }

    private List<CollectEvent> largestRound(String env) throws Exception {
        String path = System.getenv(env);
        if (path == null || path.isBlank()) {
            throw new IllegalStateException(env + " 에 덤프 경로가 필요하다");
        }
        Map<String, List<CollectEvent>> byRun = new LinkedHashMap<>();
        for (String line : Files.readAllLines(Path.of(path), StandardCharsets.UTF_8)) {
            if (!line.isBlank()) {
                CollectEvent event = json.read(line);
                byRun.computeIfAbsent(String.valueOf(event.pollRunAt()), k -> new ArrayList<>()).add(event);
            }
        }
        return byRun.values().stream().max((a, b) -> Integer.compare(a.size(), b.size())).orElseThrow();
    }

    private static List<Integer> intList(String env, String fallback) {
        List<Integer> out = new ArrayList<>();
        for (String part : System.getenv().getOrDefault(env, fallback).split(",")) {
            out.add(Integer.parseInt(part.trim()));
        }
        return out;
    }

    private static Map<String, Object> producerConfig() {
        Map<String, Object> config = new HashMap<>();
        config.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, BOOTSTRAP);
        config.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
        config.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
        config.put(ProducerConfig.ACKS_CONFIG, "all");
        config.put(ProducerConfig.LINGER_MS_CONFIG, 20);
        config.put(ProducerConfig.BATCH_SIZE_CONFIG, 64 * 1024);
        config.put(ProducerConfig.COMPRESSION_TYPE_CONFIG, "lz4");
        return config;
    }

    private static Consumer<String, String> consumer(String group) {
        Map<String, Object> config = new HashMap<>();
        config.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, BOOTSTRAP);
        config.put(ConsumerConfig.GROUP_ID_CONFIG, group);
        config.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
        config.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
        config.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
        config.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, false);
        config.put(ConsumerConfig.MAX_POLL_RECORDS_CONFIG, MAX_POLL_RECORDS);
        return new KafkaConsumer<>(config);
    }

    private record Rounds(List<CollectEvent> subway, List<CollectEvent> bike) {
    }

    /**
     * @param stale 마지막 회차 값이 아닌 따릉이 대여소 수. 0 이어야 유실 0
     */
    private record Drain(long events, long consumed, long failed, long stale, int bikeStations, long millis,
                         long joinMillis) {
        String lossLine() {
            return (consumed == events && failed == 0 && stale == 0)
                    ? "0건 (소화 %,d = 적재 %,d · 실패 0 · 대여소 %,d곳 전부 마지막 회차)".formatted(consumed, events, bikeStations)
                    : "소화 %,d / 적재 %,d · 실패 %,d · 마지막 회차 아님 %,d곳".formatted(consumed, events, failed, stale);
        }
    }
}
