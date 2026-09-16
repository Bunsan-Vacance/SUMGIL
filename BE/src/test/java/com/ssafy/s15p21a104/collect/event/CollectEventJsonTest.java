package com.ssafy.s15p21a104.collect.event;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
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

    // ── read: 컨슈머(S15P21A104-171)가 같은 계약으로 되읽는다 ──────────────────────────

    @Test
    @DisplayName("write 한 이벤트를 read 하면 모든 필드가 그대로 돌아온다 (지하철)")
    void 왕복_지하철() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("statnId", "1009000937");
        row.put("statnNm", "둔촌오륜");
        row.put("barvlDt", "20");
        CollectEvent event = new CollectEvent("e1", "subway.arrival", "1009000937",
                OffsetDateTime.parse("2026-09-14T11:46:06+09:00"),
                OffsetDateTime.parse("2026-09-14T11:50:21.461+09:00"),
                OffsetDateTime.parse("2026-09-14T11:50:21+09:00"), row);

        CollectEvent back = json.read(json.write(event));

        assertEquals(event.eventId(), back.eventId());
        assertEquals(event.source(), back.source());
        assertEquals(event.entityId(), back.entityId());
        assertEquals(event.sourceGeneratedAt(), back.sourceGeneratedAt());
        assertEquals(event.ingestedAt(), back.ingestedAt());
        assertEquals(event.pollRunAt(), back.pollRunAt());
        assertEquals(event.payload(), back.payload());
    }

    @Test
    @DisplayName("source_generated_at 이 null 인 따릉이 이벤트도 왕복한다")
    void 왕복_따릉이_생성시각_없음() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("stationId", "ST-1577");
        row.put("parkingBikeTotCnt", "6");
        CollectEvent event = new CollectEvent("e2", "bike.stock", "ST-1577", null,
                OffsetDateTime.parse("2026-09-15T13:09:17.001+09:00"),
                OffsetDateTime.parse("2026-09-15T13:09:17+09:00"), row);

        CollectEvent back = json.read(json.write(event));

        assertNull(back.sourceGeneratedAt(), "없는 시각은 null 로 되읽는다");
        assertEquals(event.ingestedAt(), back.ingestedAt());
        assertEquals(event.payload(), back.payload());
    }

    @Test
    @DisplayName("payload 의 null 필드가 read 뒤에도 남는다 — 키가 사라지면 안 된다")
    void read_payload_null_유지() {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("subwayNm", null);
        row.put("statnId", "1002000222");
        CollectEvent event = new CollectEvent("e3", "subway.arrival", "1002000222", null,
                OffsetDateTime.parse("2026-09-16T10:31:00+09:00"),
                OffsetDateTime.parse("2026-09-16T10:31:00+09:00"), row);

        CollectEvent back = json.read(json.write(event));

        assertTrue(back.payload().containsKey("subwayNm"), "null 값이어도 키는 남아야 한다");
        assertNull(back.payload().get("subwayNm"));
    }

    @Test
    @DisplayName("계약에 없는 필드가 섞여 와도 무시하고 읽는다 — 뒤에 필드가 늘어도 컨슈머가 죽지 않는다")
    void read_알수없는_필드_무시() {
        String text = """
                {"event_id":"e4","source":"bike.stock","entity_id":"ST-9","source_generated_at":null,
                 "ingested_at":"2026-09-16T10:00:00+09:00","poll_run_at":"2026-09-16T10:00:00+09:00",
                 "payload":{"stationId":"ST-9"},"schema_version":2}""";

        CollectEvent back = json.read(text);

        assertEquals("e4", back.eventId());
        assertEquals("ST-9", back.entityId());
        assertEquals(Map.of("stationId", "ST-9"), back.payload());
    }

    @Test
    @DisplayName("JSON 이 아니면 예외 — 조용히 빈 이벤트를 만들지 않는다")
    void read_깨진_JSON() {
        assertThrows(RuntimeException.class, () -> json.read("깨진 문자열"));
    }
}
