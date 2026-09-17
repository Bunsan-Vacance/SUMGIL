package com.ssafy.s15p21a104.collect.publish;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.collect.SourcePoller;
import java.util.List;
import lombok.extern.slf4j.Slf4j;

/**
 * 수집 → Redis 적재 → Kafka 적재 순으로 한 회차를 두 곳에 반영한다 (BIKE-001 156).
 *
 * <p>Redis 적재는 프론트 실시간 조회용 캐시를 최신으로 유지하기 위한 보너스 경로라 실패해도 회차를 막지 않는다 —
 * 로그만 남기고 Kafka 전송(AI 컨슈머로 가는 원천 경로)은 그대로 이어간다. 성공·실패 판정과 반환값은 Kafka 쪽만 따른다 —
 * {@link SourcePoller}의 서킷 브레이커·재시도 로직이 원래도 Kafka 실패 기준으로 동작했으므로 그 기준을 그대로 유지한다.
 */
@Slf4j
public final class CompositeEventPublisher implements EventPublisher {

    private final EventPublisher primary;
    private final EventPublisher redis;

    public CompositeEventPublisher(EventPublisher primary, EventPublisher redis) {
        this.primary = primary;
        this.redis = redis;
    }

    @Override
    public int publish(String topic, List<CollectEvent> events) {
        try {
            redis.publish(topic, events);
        } catch (RuntimeException e) {
            log.warn("{} Redis 적재 실패 — Kafka 전송은 계속한다: {}", topic, e.getMessage());
        }
        return primary.publish(topic, events);
    }
}
