package com.ssafy.s15p21a104.collect.publish;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.consume.ApplyResult;
import com.ssafy.s15p21a104.consume.EventApplier;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.extern.slf4j.Slf4j;

/**
 * Kafka 를 건너뛰고 수집기가 Redis 에 바로 반영하는 경로 (S15P21A104-171 보험 스위치).
 * {@code collect.publisher=redis} 일 때만 만들어진다.
 *
 * <p>두 가지 용도다.
 * <ul>
 *   <li><b>보험</b> — Kafka 가 죽었을 때 발표 직전에 되돌릴 경로 (티켓 본문 요구사항)</li>
 *   <li><b>측정</b> — {@code perf/README.md} 원칙 2 가 요구하는 "예전 경로를 스위치로 남겨 같은 조건에서 다시 재기".
 *       Kafka 경유와 이 경로의 차이가 곧 <b>Kafka 가 얹은 비용</b>이다. 개선이 아니라 비용 측정이라는 점을 분명히 해둔다 —
 *       홉이 하나 줄었으니 직접 쓰기가 당연히 빠르다. Kafka 의 값어치는 지연이 아니라
 *       AI 컨슈머({@code ai-spark})가 같은 이벤트를 따로 받는 것과, 컨슈머가 죽어도 48시간치를 따라잡는 것이다.</li>
 * </ul>
 *
 * <p>반영 로직은 컨슈머와 <b>같은 반영기</b>를 쓴다. 두 경로가 다른 값을 쓰면 스위치를 돌린 순간 서비스가 달라진다.
 */
@Slf4j
public final class RedisApplyingPublisher implements EventPublisher {

    private final Map<String, EventApplier> byTopic;

    public RedisApplyingPublisher(List<EventApplier> appliers) {
        Map<String, EventApplier> map = new LinkedHashMap<>();
        for (EventApplier applier : appliers) {
            map.put(applier.topic(), applier);
        }
        this.byTopic = Map.copyOf(map);
    }

    /** @return 반영한 건수. 브로커가 없으므로 "전송 확인" 대신 "Redis 에 쓴 건수" 다 */
    @Override
    public int publish(String topic, List<CollectEvent> events) {
        if (events.isEmpty()) {
            return 0;
        }
        EventApplier applier = byTopic.get(topic);
        if (applier == null) {
            // 반영기가 없는 토픽(weather.nowcast). Kafka 경유라면 AI 가 받지만 이 경로에는 받는 쪽이 없다.
            log.warn("{} 반영기가 없다 — {}건을 Redis 에 쓰지 않는다 (collect.publisher=redis 의 한계)", topic, events.size());
            return 0;
        }
        try {
            ApplyResult result = applier.apply(events);
            return result.written();
        } catch (RuntimeException e) {
            throw new PublishException("%s 반영 실패 (%d건)".formatted(topic, events.size()), 0, events.size(), e);
        }
    }
}
