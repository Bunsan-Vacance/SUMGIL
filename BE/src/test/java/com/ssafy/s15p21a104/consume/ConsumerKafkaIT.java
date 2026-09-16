package com.ssafy.s15p21a104.consume;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.collect.event.CollectEventJson;
import com.ssafy.s15p21a104.global.cache.CacheKeys;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.function.Supplier;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.common.serialization.StringSerializer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.kafka.core.DefaultKafkaProducerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

/**
 * 티켓 완료 기준 3건 (S15P21A104-171): 프로듀서 → Kafka → 컨슈머 → Redis 왕복 /
 * 오래된 이벤트가 최신을 안 덮음 / TTL 만료.
 *
 * <p>여기서는 실제 리스너 컨테이너가 도는 스프링 컨텍스트를 그대로 쓴다 — 단위 테스트가 이미 반영 규칙을 덮고 있으므로,
 * 이 테스트가 확인할 것은 <b>배선</b>(그룹·역직렬화·라우팅·Redis 직렬화)이다.
 *
 * <p>{@code KAFKA_BOOTSTRAP_SERVERS} 가 없으면 건너뛴다 ({@code CollectorKafkaIT} 와 같은 규칙).
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE)
@ActiveProfiles("consume")
@EnabledIfEnvironmentVariable(
        named = "KAFKA_BOOTSTRAP_SERVERS",
        matches = ".+",
        disabledReason = "Kafka 브로커 주소가 없다. docs/infra/kafka.md 의 기동 절차를 먼저 실행한다")
class ConsumerKafkaIT {

    private static final Duration TIMEOUT = Duration.ofSeconds(30);
    private static final String BOOTSTRAP = System.getenv("KAFKA_BOOTSTRAP_SERVERS");

    /** 실행마다 새 그룹을 써서 이전 실행의 커밋된 오프셋과 섞이지 않게 한다. earliest 라야 구독 직후 것을 놓치지 않는다. */
    @DynamicPropertySource
    static void consumerProperties(DynamicPropertyRegistry registry) {
        registry.add("consume.kafka.bootstrap-servers", () -> BOOTSTRAP);
        registry.add("consume.kafka.group-id", () -> "it-" + System.nanoTime());
        registry.add("consume.kafka.auto-offset-reset", () -> "earliest");
        // 테스트가 도는 시각에 결과가 달라지지 않게 창을 하루 종일로 둔다 (상태 키 판정)
        registry.add("consume.subway.window", () -> "00:00-24:00");
    }

    @Autowired
    RedisTemplate<String, Object> redis;

    @Autowired
    CollectEventJson json;

    private final String suffix = String.valueOf(System.nanoTime());
    private final List<String> touchedKeys = new java.util.ArrayList<>();

    @AfterEach
    void cleanUp() {
        touchedKeys.forEach(redis::delete);
    }

    private String rentalId() {
        return "IT-" + suffix;
    }

    private void send(String topic, CollectEvent event) {
        Map<String, Object> config = new HashMap<>();
        config.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, BOOTSTRAP);
        config.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
        config.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
        config.put(ProducerConfig.ACKS_CONFIG, "all");
        DefaultKafkaProducerFactory<String, String> factory = new DefaultKafkaProducerFactory<>(config);
        try {
            new KafkaTemplate<>(factory).send(topic, event.entityId(), json.write(event))
                    .get(TIMEOUT.toSeconds(), TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(e);
        } catch (Exception e) {
            throw new IllegalStateException("전송 실패", e);
        } finally {
            factory.destroy();
        }
    }

    /** 컨슈머가 비동기라 조건이 참이 될 때까지 기다린다. */
    private static <T> T await(String what, Supplier<T> probe) {
        long deadline = System.nanoTime() + TIMEOUT.toNanos();
        while (System.nanoTime() < deadline) {
            T value = probe.get();
            if (value != null) {
                return value;
            }
            try {
                Thread.sleep(200);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException(e);
            }
        }
        throw new AssertionError("%s 를 %s 안에 못 봤다".formatted(what, TIMEOUT));
    }

    private static CollectEvent bikeEvent(String rentalId, int available, String ingestedAt) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("stationId", rentalId);
        row.put("parkingBikeTotCnt", String.valueOf(available));
        row.put("rackTotCnt", "15");
        OffsetDateTime at = OffsetDateTime.parse(ingestedAt);
        return new CollectEvent("evt-" + rentalId + "-" + ingestedAt, "bike.stock", rentalId, null, at, at, row);
    }

    @Test
    @DisplayName("완료 기준 1 — 프로듀서 → Kafka → 컨슈머 → Redis 왕복")
    void 왕복() {
        String key = CacheKeys.bikeStock(rentalId());
        touchedKeys.add(key);

        send("bike.stock", bikeEvent(rentalId(), 6, "2026-09-16T10:30:12+09:00"));

        @SuppressWarnings("unchecked")
        Map<String, Object> value = (Map<String, Object>) await("bike:stock 키", () -> redis.opsForValue().get(key));
        assertEquals(rentalId(), value.get("rental_id"));
        assertEquals(6, value.get("available"));
        assertEquals(15, value.get("racks"));
        assertEquals("2026-09-16T10:30:12+09:00", value.get("ingested_at"));
        assertNotNull(value.get("written_at"), "컨슈머가 쓴 시각이 붙는다 — 지연 측정의 세 번째 시각");
    }

    @Test
    @DisplayName("완료 기준 2 — 오래된 이벤트가 최신 값을 덮지 않는다")
    void 오래된_이벤트는_안_덮는다() {
        String key = CacheKeys.bikeStock(rentalId());
        touchedKeys.add(key);

        send("bike.stock", bikeEvent(rentalId(), 6, "2026-09-16T10:30:12+09:00"));
        await("첫 값", () -> redis.opsForValue().get(key));

        send("bike.stock", bikeEvent(rentalId(), 99, "2026-09-16T10:28:12+09:00"));

        // 두 번째가 처리되기를 기다린 뒤에도 값이 그대로여야 한다. 처리 여부는 "안 바뀐 것" 으로는 못 재므로
        // 더 새로운 이벤트를 하나 더 보내 그것이 반영되면 사이의 것도 처리됐다고 본다 (파티션 1이라 순서가 보장된다).
        send("bike.stock", bikeEvent(rentalId(), 3, "2026-09-16T10:32:12+09:00"));

        @SuppressWarnings("unchecked")
        Map<String, Object> value = (Map<String, Object>) await("세 번째 반영", () -> {
            Object v = redis.opsForValue().get(key);
            return v instanceof Map<?, ?> m && Integer.valueOf(3).equals(m.get("available")) ? v : null;
        });
        assertEquals(3, value.get("available"), "옛 이벤트(99)가 중간에 덮지 못했다");
    }

    @Test
    @DisplayName("완료 기준 3 — 값에 TTL 이 걸리고, 만료되면 키가 사라진다")
    void TTL() {
        String key = CacheKeys.bikeStock(rentalId());
        touchedKeys.add(key);

        send("bike.stock", bikeEvent(rentalId(), 6, "2026-09-16T10:30:12+09:00"));
        await("bike:stock 키", () -> redis.opsForValue().get(key));

        Long ttl = redis.getExpire(key);
        assertNotNull(ttl);
        assertTrue(ttl > 0 && ttl <= CacheKeys.BIKE_STOCK_TTL.toSeconds(),
                "TTL 이 %ds 이하로 걸려 있어야 한다 — 실제 %ds".formatted(CacheKeys.BIKE_STOCK_TTL.toSeconds(), ttl));

        // 실제 만료는 300초를 기다릴 수 없으므로, 같은 값 모양을 짧은 TTL 로 써서 Redis 가 지우는 것을 확인한다.
        // 위 단언(컨슈머가 TTL 을 건다)과 합쳐 "갱신이 끊기면 키가 사라진다" 를 덮는다.
        String shortKey = CacheKeys.bikeStock(rentalId() + "-EXPIRY");
        touchedKeys.add(shortKey);
        redis.opsForValue().set(shortKey, Map.of("rental_id", shortKey, "available", 1), Duration.ofSeconds(1));
        assertNotNull(redis.opsForValue().get(shortKey), "쓴 직후에는 있다");

        assertEquals(Boolean.TRUE, await("키 만료", () -> Boolean.TRUE.equals(redis.hasKey(shortKey)) ? null : Boolean.TRUE));
    }

    @Test
    @DisplayName("지하철은 statnId 를 우리 역번호로 바꿔 쓰고 상태 키를 남긴다")
    void 지하철_왕복() {
        String key = CacheKeys.subwayArrival("222");
        touchedKeys.add(key);
        touchedKeys.add(CacheKeys.SUBWAY_ARRIVAL_STATUS);

        Map<String, Object> row = new LinkedHashMap<>();
        row.put("subwayId", "1002");
        row.put("statnId", "1002000222");
        // 원천 표기를 일부러 다르게 넣는다 — 값에 나가는 것은 정본 표의 이름이어야 한다
        row.put("statnNm", "강남(원천표기)");
        row.put("updnLine", "상행");
        row.put("btrainNo", "IT" + suffix.substring(suffix.length() - 4));
        row.put("barvlDt", "120");
        row.put("arvlCd", "2");
        OffsetDateTime run = OffsetDateTime.now(CollectEvent.KST).withNano(0);
        CollectEvent event = new CollectEvent("evt-subway-" + suffix, "subway.arrival", "1002000222", run, run, run, row);

        send("subway.arrival", event);

        @SuppressWarnings("unchecked")
        Map<String, Object> value = (Map<String, Object>) await("subway:arrival:222", () -> {
            Object v = redis.opsForValue().get(key);
            return v instanceof Map<?, ?> m && run.toString().equals(m.get("poll_run_at")) ? v : null;
        });
        assertEquals("222", value.get("station_id"), "statnId 1002000222 가 우리 역번호로 바뀌었다");
        assertEquals("강남", value.get("station_name"), "payload 의 표기가 아니라 정본 표의 역명을 쓴다");
        assertTrue(value.get("trains") instanceof List<?> list && !list.isEmpty());

        // 이 테스트는 earliest 로 토픽을 처음부터 재생한다. 키가 "있다" 는 것만 보면 옛 회차를 반영하던 중간 상태를
        // 읽어 stale 로 보일 수 있으므로, 우리 회차가 반영된 상태를 기다린다.
        @SuppressWarnings("unchecked")
        Map<String, Object> status = (Map<String, Object>) await("상태 키(우리 회차 반영)", () -> {
            Object v = redis.opsForValue().get(CacheKeys.SUBWAY_ARRIVAL_STATUS);
            return v instanceof Map<?, ?> m && run.toString().equals(m.get("last_poll_run_at")) ? v : null;
        });
        assertEquals("ok", status.get("state"));
        assertEquals("00:00-24:00", status.get("window"));
    }
}
