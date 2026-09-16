package com.ssafy.s15p21a104.collect.publish;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.consume.ApplyResult;
import com.ssafy.s15p21a104.consume.EventApplier;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 보험 스위치 (S15P21A104-171 티켓 본문: "Redis 직접 쓰기 경로를 환경변수 스위치로 남긴다").
 *
 * <p>Kafka 가 죽었을 때 발표 직전에 되돌릴 경로이자, {@code perf/README.md} 원칙 2 가 요구하는
 * "예전 경로를 스위치로 남겨 같은 조건에서 다시 잴 수 있게" 하는 장치다. 반영 로직은 컨슈머와 <b>같은 반영기</b>를 쓴다 —
 * 두 경로가 다른 값을 쓰면 스위치를 돌린 순간 서비스가 달라진다.
 */
class RedisApplyingPublisherTest {

    private static final class RecordingApplier implements EventApplier {
        private final String topic;
        final List<List<CollectEvent>> batches = new ArrayList<>();

        RecordingApplier(String topic) {
            this.topic = topic;
        }

        @Override
        public String topic() {
            return topic;
        }

        @Override
        public ApplyResult apply(List<CollectEvent> batch) {
            batches.add(List.copyOf(batch));
            return new ApplyResult(batch.size(), 0, 0);
        }
    }

    private static CollectEvent event(String topic, String entityId) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("stationId", entityId);
        OffsetDateTime at = OffsetDateTime.parse("2026-09-16T10:30:12+09:00");
        return new CollectEvent("id-" + entityId, topic, entityId, null, at, at, row);
    }

    @Test
    @DisplayName("회차를 통째로 반영기에 넘긴다 — 한 번만 부른다")
    void 회차를_통째로_넘긴다() {
        RecordingApplier bike = new RecordingApplier("bike.stock");
        RedisApplyingPublisher publisher = new RedisApplyingPublisher(List.of(bike));

        int applied = publisher.publish("bike.stock", List.of(event("bike.stock", "ST-1"), event("bike.stock", "ST-2")));

        assertEquals(2, applied);
        assertEquals(1, bike.batches.size(), "회차 하나에 반영기 호출 한 번");
        assertEquals(2, bike.batches.get(0).size());
    }

    @Test
    @DisplayName("반영기가 없는 토픽은 조용히 버리지 않고 0 을 돌려준다 — 수집기 로그에 전송 0건으로 남는다")
    void 반영기_없는_토픽() {
        RedisApplyingPublisher publisher = new RedisApplyingPublisher(List.of(new RecordingApplier("bike.stock")));

        assertEquals(0, publisher.publish("weather.nowcast", List.of(event("weather.nowcast", "60:127:T1H"))));
    }

    @Test
    void 빈_회차는_아무것도_안_한다() {
        RecordingApplier bike = new RecordingApplier("bike.stock");

        assertEquals(0, new RedisApplyingPublisher(List.of(bike)).publish("bike.stock", List.of()));
        assertTrue(bike.batches.isEmpty());
    }

    @Test
    @DisplayName("반영기가 터지면 PublishException — 수집기가 서킷에 세지 않고 다음 회차에 계속한다")
    void 반영기_예외는_PublishException() {
        EventApplier boom = new EventApplier() {
            @Override
            public String topic() {
                return "bike.stock";
            }

            @Override
            public ApplyResult apply(List<CollectEvent> batch) {
                throw new IllegalStateException("Redis 다운");
            }
        };
        RedisApplyingPublisher publisher = new RedisApplyingPublisher(List.of(boom));

        PublishException thrown = org.junit.jupiter.api.Assertions.assertThrows(PublishException.class,
                () -> publisher.publish("bike.stock", List.of(event("bike.stock", "ST-1"))));
        assertEquals(0, thrown.sent());
        assertEquals(1, thrown.failed());
    }
}
