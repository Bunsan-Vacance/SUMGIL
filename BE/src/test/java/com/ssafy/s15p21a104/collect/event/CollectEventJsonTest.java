package com.ssafy.s15p21a104.collect.event;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.json.JsonMapper;

class CollectEventJsonTest {

    private final JsonMapper mapper = JsonMapper.builder().build();
    private final CollectEventJson json = new CollectEventJson(mapper);

    @Test
    @DisplayName("계약 필드 7개가 snake_case 로, 문서와 같은 순서로 나간다")
    void 계약_필드와_순서() {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("stationId", "ST-4");
        payload.put("parkingBikeTotCnt", "5");
        CollectEvent event = new CollectEvent("abc", "bike.stock", "ST-4", null,
                OffsetDateTime.parse("2026-09-14T09:00:03.123456+09:00"),
                OffsetDateTime.parse("2026-09-14T09:00:00+09:00"), payload);

        Map<String, Object> out = mapper.readValue(json.write(event), new TypeReference<Map<String, Object>>() {
        });

        assertEquals(List.of("event_id", "source", "entity_id", "source_generated_at", "ingested_at", "poll_run_at",
                "payload"), List.copyOf(out.keySet()));
        assertEquals("abc", out.get("event_id"));
        assertEquals("bike.stock", out.get("source"));
        assertEquals("ST-4", out.get("entity_id"));
        assertTrue(out.containsKey("source_generated_at"), "따릉이는 생성시각이 없어도 키는 있어야 한다");
        assertNull(out.get("source_generated_at"));
        assertEquals("2026-09-14T09:00:03.123+09:00", out.get("ingested_at"));
        assertEquals("2026-09-14T09:00:00+09:00", out.get("poll_run_at"));
        assertEquals(Map.of("stationId", "ST-4", "parkingBikeTotCnt", "5"), out.get("payload"));
    }

    @Test
    void payload_는_원본_그대로_null_포함() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("subwayNm", null);
        row.put("statnId", "1009000937");
        CollectEvent event = new CollectEvent("id", "subway.arrival", "1009000937",
                OffsetDateTime.parse("2026-09-08T11:24:09+09:00"), OffsetDateTime.parse("2026-09-08T11:25:00+09:00"),
                OffsetDateTime.parse("2026-09-08T11:25:00+09:00"), row);

        String text = json.write(event);

        assertTrue(text.contains("\"subwayNm\":null"));
        assertTrue(text.contains("\"source_generated_at\":\"2026-09-08T11:24:09+09:00\""));
    }
}
