package com.ssafy.s15p21a104.consume;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.collect.event.CollectEventJson;
import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

/**
 * 배치 하나를 토픽별 반영기로 보내고, 구간별 지연을 재는 부분 (S15P21A104-171).
 * Kafka 타입에 기대지 않는다 — {@link RawRecord} 로 받아서 브로커 없이 단위 테스트한다.
 */
class BatchDispatcherTest {

    /** KST 2026-09-16 10:31:05.000 */
    private static final Instant NOW = Instant.parse("2026-09-16T01:31:05Z");
    private static final Clock CLOCK = Clock.fixed(NOW, ZoneOffset.UTC);

    private final CollectEventJson json = new CollectEventJson(JsonMapper.builder().build());

    /** 무엇을 받았는지만 기록하는 반영기. */
    private static final class RecordingApplier implements EventApplier {
        private final String topic;
        final List<CollectEvent> received = new ArrayList<>();

        RecordingApplier(String topic) {
            this.topic = topic;
        }

        @Override
        public String topic() {
            return topic;
        }

        @Override
        public ApplyResult apply(List<CollectEvent> batch) {
            received.addAll(batch);
            return new ApplyResult(batch.size(), 0, 0);
        }
    }

    private final RecordingApplier bike = new RecordingApplier("bike.stock");
    private final RecordingApplier subway = new RecordingApplier("subway.arrival");
    private final BatchDispatcher dispatcher = new BatchDispatcher(List.of(bike, subway), json, CLOCK);

    private String eventJson(String topic, String entityId, String ingestedAt) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("stationId", entityId);
        OffsetDateTime at = OffsetDateTime.parse(ingestedAt);
        return json.write(new CollectEvent("id-" + entityId, topic, entityId, null, at, at, row));
    }

    private static long millis(String kst) {
        return OffsetDateTime.parse(kst).toInstant().toEpochMilli();
    }

    @Test
    @DisplayName("토픽별로 알맞은 반영기에 보낸다")
    void 토픽_라우팅() {
        DispatchResult result = dispatcher.dispatch(List.of(
                new RawRecord("bike.stock", eventJson("bike.stock", "ST-1", "2026-09-16T10:31:00+09:00"),
                        millis("2026-09-16T10:31:01+09:00")),
                new RawRecord("subway.arrival", eventJson("subway.arrival", "1002000222", "2026-09-16T10:31:00+09:00"),
                        millis("2026-09-16T10:31:01+09:00"))));

        assertEquals(1, bike.received.size());
        assertEquals(1, subway.received.size());
        assertEquals(2, result.applied().written());
        assertEquals(0, result.failed());
    }

    @Test
    @DisplayName("한 배치를 반영기당 한 번만 부른다 — 건별로 부르면 Redis 왕복이 건수만큼 난다")
    void 반영기당_한_번() {
        List<RawRecord> records = new ArrayList<>();
        for (int i = 0; i < 5; i++) {
            records.add(new RawRecord("bike.stock", eventJson("bike.stock", "ST-" + i, "2026-09-16T10:31:00+09:00"),
                    millis("2026-09-16T10:31:01+09:00")));
        }

        dispatcher.dispatch(records);

        assertEquals(5, bike.received.size(), "5건이 한 번에 들어갔다");
    }

    @Test
    @DisplayName("깨진 레코드 한 건이 배치 전체를 죽이지 않는다")
    void 깨진_레코드는_그_건만() {
        DispatchResult result = dispatcher.dispatch(List.of(
                new RawRecord("bike.stock", "깨진 문자열", millis("2026-09-16T10:31:01+09:00")),
                new RawRecord("bike.stock", eventJson("bike.stock", "ST-2", "2026-09-16T10:31:00+09:00"),
                        millis("2026-09-16T10:31:01+09:00"))));

        assertEquals(1, result.failed());
        assertEquals(1, bike.received.size(), "멀쩡한 건은 반영된다");
    }

    @Test
    @DisplayName("반영기가 없는 토픽은 세기만 하고 버린다")
    void 모르는_토픽() {
        DispatchResult result = dispatcher.dispatch(List.of(
                new RawRecord("weather.nowcast", eventJson("weather.nowcast", "60:127:T1H", "2026-09-16T10:31:00+09:00"),
                        millis("2026-09-16T10:31:01+09:00"))));

        assertEquals(1, result.ignored());
        assertTrue(bike.received.isEmpty());
        assertTrue(subway.received.isEmpty());
    }

    @Test
    @DisplayName("지연을 두 구간으로 나눠 잰다 — produce 는 Kafka 몫, consume 은 우리 몫")
    void 구간별_지연() {
        // ingested_at 10:31:00.000 → 레코드 timestamp 10:31:01.500 → written_at(고정 시계) 10:31:05.000
        DispatchResult result = dispatcher.dispatch(List.of(
                new RawRecord("bike.stock", eventJson("bike.stock", "ST-1", "2026-09-16T10:31:00+09:00"),
                        millis("2026-09-16T10:31:01.500+09:00"))));

        assertEquals(1, result.produce().count());
        assertEquals(1500, result.produce().median(), "ingested_at → 레코드 timestamp");
        assertEquals(3500, result.consume().median(), "레코드 timestamp → written_at");
    }

    @Test
    void 빈_배치는_아무것도_안_한다() {
        DispatchResult result = dispatcher.dispatch(List.of());

        assertEquals(ApplyResult.NOTHING, result.applied());
        assertEquals(0, result.failed());
        assertEquals(LatencyStats.EMPTY, result.produce());
    }
}
