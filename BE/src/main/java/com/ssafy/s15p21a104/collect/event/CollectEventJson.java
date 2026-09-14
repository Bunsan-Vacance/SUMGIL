package com.ssafy.s15p21a104.collect.event;

import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.LinkedHashMap;
import java.util.Map;
import tools.jackson.databind.json.JsonMapper;

/**
 * {@link CollectEvent} → 와이어 JSON. 필드 이름은 계약(snake_case) 그대로이고 순서도 문서와 같다.
 *
 * <p>애노테이션 대신 맵을 직접 만든다 — Boot 4 의 Jackson 3 과 Jackson 2 애노테이션 패키지가 섞이는 것을 피하고,
 * 다른 언어(AI 파이썬 컨슈머)가 읽을 형식을 코드에서 한눈에 보이게 하려는 것이다.
 * 시각은 ISO-8601 + 오프셋(예: {@code 2026-09-14T09:00:03+09:00}) 이고 밀리초 이하는 잘라낸다.
 */
public final class CollectEventJson {

    private static final DateTimeFormatter TIME = DateTimeFormatter.ISO_OFFSET_DATE_TIME;

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

    static String format(OffsetDateTime time) {
        return time == null ? null : TIME.format(time.truncatedTo(ChronoUnit.MILLIS));
    }
}
