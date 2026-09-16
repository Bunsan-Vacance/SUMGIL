package com.ssafy.s15p21a104.collect.event;

import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.LinkedHashMap;
import java.util.Map;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.json.JsonMapper;

/**
 * {@link CollectEvent} ↔ 와이어 JSON. 필드 이름은 계약(snake_case) 그대로이고 순서도 문서와 같다.
 *
 * <p>애노테이션 대신 맵을 직접 만든다 — Boot 4 의 Jackson 3 과 Jackson 2 애노테이션 패키지가 섞이는 것을 피하고,
 * 다른 언어(AI 파이썬 컨슈머)가 읽을 형식을 코드에서 한눈에 보이게 하려는 것이다.
 * 시각은 ISO-8601 + 오프셋(예: {@code 2026-09-14T09:00:03+09:00}) 이고 밀리초 이하는 잘라낸다.
 *
 * <p>{@link #write} 는 수집기(169)가, {@link #read} 는 Redis 반영 컨슈머(171)가 쓴다. 같은 계약의 양쪽이라
 * 한 파일에 둔다 — 한쪽만 고치면 왕복이 깨지는 것을 눈으로 막는다.
 */
public final class CollectEventJson {

    private static final DateTimeFormatter TIME = DateTimeFormatter.ISO_OFFSET_DATE_TIME;
    private static final TypeReference<Map<String, Object>> MAP = new TypeReference<>() {
    };

    private final JsonMapper mapper;

    public CollectEventJson(JsonMapper mapper) {
        this.mapper = mapper;
    }

    public String write(CollectEvent event) {
        return mapper.writeValueAsString(toMap(event));
    }

    public Map<String, Object> toMap(CollectEvent event) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("event_id", event.eventId());
        out.put("source", event.source());
        out.put("entity_id", event.entityId());
        out.put("source_generated_at", format(event.sourceGeneratedAt()));
        out.put("ingested_at", format(event.ingestedAt()));
        out.put("poll_run_at", format(event.pollRunAt()));
        out.put("payload", event.payload());
        return out;
    }

    /**
     * 와이어 JSON → 이벤트. 계약에 없는 최상위 필드는 무시한다 — 뒤에 필드가 늘어도 컨슈머가 죽지 않게.
     * {@code payload} 는 원본 그대로 두고(값이 null 인 키도 남긴다) 해석은 반영기가 한다.
     *
     * @throws tools.jackson.core.JacksonException JSON 이 아니거나 최상위가 객체가 아니면
     */
    public CollectEvent read(String text) {
        Map<String, Object> in = mapper.readValue(text, MAP);
        return new CollectEvent(
                text(in.get("event_id")),
                text(in.get("source")),
                text(in.get("entity_id")),
                parse(in.get("source_generated_at")),
                parse(in.get("ingested_at")),
                parse(in.get("poll_run_at")),
                payload(in.get("payload")));
    }

    static String format(OffsetDateTime time) {
        return time == null ? null : TIME.format(time.truncatedTo(ChronoUnit.MILLIS));
    }

    static OffsetDateTime parse(Object value) {
        return value == null ? null : OffsetDateTime.parse(value.toString(), TIME);
    }

    private static String text(Object value) {
        return value == null ? null : value.toString();
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> payload(Object value) {
        return value instanceof Map<?, ?> map ? (Map<String, Object>) map : Map.of();
    }
}
