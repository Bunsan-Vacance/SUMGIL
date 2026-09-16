package com.ssafy.s15p21a104.collect.event;

import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Kafka 에 넣는 이벤트 1건 (BE/docs/infra/kafka.md 4절 계약 — 2026-09-08 AI팀 합의, 2026-09-14 poll_run_at 추가).
 *
 * @param eventId           {@code source + entity_id + source_generated_at + payload_hash} 의 SHA-256 (NFR-STREAM-006)
 * @param source            토픽 이름과 같다 — subway.arrival · bike.stock · weather.nowcast
 * @param entityId          원천의 개체 식별자. 지하철은 {@code statnId}, 따릉이는 {@code stationId}(ST-xxx), 날씨는 {@code nx:ny:category}
 * @param sourceGeneratedAt 원천이 밝힌 생성 시각. 따릉이는 없어서 null 이고, 그때는 ingested_at 이 신선도 기준이다
 * @param ingestedAt        우리가 응답을 받은 시각
 * @param pollRunAt         이 이벤트가 속한 회차의 시각(초 단위). AI 가 건별 이벤트를 회차 스냅샷으로 다시 묶는 키
 * @param payload           API 응답 행 원본 그대로. 뒤에서 쓸 필드를 우리가 미리 버리지 않는다
 */
public record CollectEvent(String eventId, String source, String entityId, OffsetDateTime sourceGeneratedAt,
                           OffsetDateTime ingestedAt, OffsetDateTime pollRunAt, Map<String, Object> payload) {

    /** 원천(서울시·기상청)이 밝히는 시각은 전부 한국 표준시라 이벤트 시각도 이 존으로 통일한다. */
    public static final ZoneId KST = ZoneId.of("Asia/Seoul");

    public CollectEvent {
        // Map.copyOf 는 null 값을 거부한다. API 행에는 null 필드가 흔하다(subwayNm 등) — 순서를 지키는 복사본으로 감싼다.
        payload = Collections.unmodifiableMap(new LinkedHashMap<>(payload == null ? Map.of() : payload));
    }
}
