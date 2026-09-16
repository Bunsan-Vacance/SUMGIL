package com.ssafy.s15p21a104.collect.event;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.OffsetDateTime;
import java.util.HexFormat;
import java.util.Map;
import tools.jackson.databind.SerializationFeature;
import tools.jackson.databind.json.JsonMapper;

/**
 * event_id 생성 (NFR-STREAM-006): {@code source | entity_id | source_generated_at | payload_hash} 를 SHA-256 으로 접는다.
 *
 * <p>payload_hash 는 키를 정렬한 정규형 JSON 의 SHA-256 이라 같은 내용이면 필드 순서가 달라도 같은 값이 나온다.
 * 같은 회차를 두 번 보내거나 페이지 경계가 겹쳐 같은 행이 두 번 와도 event_id 가 같아 컨슈머가 걸러낼 수 있다.
 */
public final class EventIdFactory {

    private static final HexFormat HEX = HexFormat.of();

    private final JsonMapper canonical = JsonMapper.builder()
            .enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS)
            .build();

    public String eventId(String source, String entityId, OffsetDateTime sourceGeneratedAt,
                          Map<String, Object> payload) {
        String generated = sourceGeneratedAt == null ? "" : sourceGeneratedAt.toString();
        String material = source + '|' + entityId + '|' + generated + '|' + payloadHash(payload);
        return sha256(material);
    }

    public String payloadHash(Map<String, Object> payload) {
        return sha256(canonical.writeValueAsString(payload == null ? Map.of() : payload));
    }

    private static String sha256(String text) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HEX.formatHex(digest.digest(text.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 을 지원하지 않는 JVM", e);
        }
    }
}
