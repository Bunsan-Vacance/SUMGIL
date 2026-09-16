package com.ssafy.s15p21a104.collect.event;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class EventIdFactoryTest {

    private final EventIdFactory ids = new EventIdFactory();
    private final OffsetDateTime at = OffsetDateTime.parse("2026-09-14T09:00:00+09:00");

    @Test
    void SHA_256_16진수_64자다() {
        String id = ids.eventId("bike.stock", "ST-4", null, Map.of("parkingBikeTotCnt", "5"));

        assertEquals(64, id.length());
        assertTrue(id.matches("[0-9a-f]{64}"));
    }

    @Test
    @DisplayName("payload 필드 순서가 달라도 내용이 같으면 같은 event_id")
    void 필드_순서에_영향받지_않는다() {
        Map<String, Object> a = new LinkedHashMap<>();
        a.put("stationId", "ST-4");
        a.put("parkingBikeTotCnt", "5");
        Map<String, Object> b = new LinkedHashMap<>();
        b.put("parkingBikeTotCnt", "5");
        b.put("stationId", "ST-4");

        assertEquals(ids.eventId("bike.stock", "ST-4", null, a), ids.eventId("bike.stock", "ST-4", null, b));
    }

    @Test
    void 값이_다르면_다른_event_id() {
        Map<String, Object> five = Map.of("stationId", "ST-4", "parkingBikeTotCnt", "5");
        Map<String, Object> six = Map.of("stationId", "ST-4", "parkingBikeTotCnt", "6");

        assertNotEquals(ids.eventId("bike.stock", "ST-4", null, five), ids.eventId("bike.stock", "ST-4", null, six));
    }

    @Test
    void 생성시각과_소스도_구분한다() {
        Map<String, Object> payload = Map.of("arvlCd", "2");

        assertNotEquals(ids.eventId("subway.arrival", "1009000937", at, payload),
                ids.eventId("subway.arrival", "1009000937", at.plusSeconds(1), payload));
        assertNotEquals(ids.eventId("subway.arrival", "1009000937", at, payload),
                ids.eventId("subway.arrival", "1009000937", null, payload));
        assertNotEquals(ids.eventId("subway.arrival", "x", at, payload), ids.eventId("bike.stock", "x", at, payload));
    }

    @Test
    void null_값이_섞인_payload_도_해시한다() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("subwayNm", null);
        row.put("statnId", "1009000937");

        assertEquals(64, ids.eventId("subway.arrival", "1009000937", at, row).length());
    }
}
