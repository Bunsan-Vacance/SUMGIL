package com.ssafy.s15p21a104.collect.publish;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 수집 → Redis → Kafka 동시 적재(BIKE-001 156). Redis 는 보너스 캐시라 실패해도 Kafka 전송은 이어져야 한다.
 */
class CompositeEventPublisherTest {

    private static final class RecordingPublisher implements EventPublisher {
        final List<List<CollectEvent>> calls = new ArrayList<>();
        RuntimeException toThrow;
        int toReturn;

        @Override
        public int publish(String topic, List<CollectEvent> events) {
            calls.add(List.copyOf(events));
            if (toThrow != null) {
                throw toThrow;
            }
            return toReturn;
        }
    }

    private static CollectEvent event(String entityId) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("stationId", entityId);
        OffsetDateTime at = OffsetDateTime.parse("2026-09-17T10:00:00+09:00");
        return new CollectEvent("id-" + entityId, "bike.stock", entityId, null, at, at, row);
    }

    @Test
    @DisplayName("Redis 먼저, 그다음 Kafka — 둘 다 정상이면 Kafka 전송 건수를 돌려준다")
    void 순서대로_반영하고_Kafka_건수를_반환한다() {
        RecordingPublisher redis = new RecordingPublisher();
        RecordingPublisher kafka = new RecordingPublisher();
        kafka.toReturn = 2;
        CompositeEventPublisher composite = new CompositeEventPublisher(kafka, redis);

        int sent = composite.publish("bike.stock", List.of(event("ST-1"), event("ST-2")));

        assertEquals(2, sent);
        assertEquals(1, redis.calls.size());
        assertEquals(1, kafka.calls.size());
    }

    @Test
    @DisplayName("Redis 적재가 실패해도 Kafka 전송은 그대로 진행된다")
    void Redis_실패해도_Kafka는_계속() {
        RecordingPublisher redis = new RecordingPublisher();
        redis.toThrow = new IllegalStateException("Redis 다운");
        RecordingPublisher kafka = new RecordingPublisher();
        kafka.toReturn = 1;
        CompositeEventPublisher composite = new CompositeEventPublisher(kafka, redis);

        int sent = composite.publish("bike.stock", List.of(event("ST-1")));

        assertEquals(1, sent);
        assertEquals(1, kafka.calls.size(), "Redis가 터져도 Kafka는 호출된다");
    }

    @Test
    @DisplayName("Kafka 전송이 실패하면 PublishException이 그대로 올라간다")
    void Kafka_실패는_그대로_전파() {
        RecordingPublisher redis = new RecordingPublisher();
        RecordingPublisher kafka = new RecordingPublisher();
        kafka.toThrow = new PublishException("전송 실패", 0, 1, null);
        CompositeEventPublisher composite = new CompositeEventPublisher(kafka, redis);

        assertThrows(PublishException.class, () -> composite.publish("bike.stock", List.of(event("ST-1"))));
        assertTrue(redis.calls.size() == 1, "Kafka 실패 전에 Redis는 이미 시도됐다");
    }
}
