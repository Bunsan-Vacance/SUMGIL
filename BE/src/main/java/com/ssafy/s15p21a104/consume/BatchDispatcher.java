package com.ssafy.s15p21a104.consume;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.collect.event.CollectEventJson;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.extern.slf4j.Slf4j;

/**
 * 배치 하나를 토픽별 반영기로 보내고 구간별 지연을 재는 곳 (S15P21A104-171).
 *
 * <p>반영기는 토픽당 <b>한 번만</b> 부른다 — 건별로 부르면 지하철 회차(약 3,000건)가 Redis 왕복 3,000번이 된다.
 *
 * <p>깨진 레코드 한 건이 배치를 죽이지 않는다. 수집기의 {@code SourcePoller.tick} 과 같은 하드 룰이다 —
 * 스트림 처리는 실패해도 프로세스가 멈추면 안 된다.
 */
@Slf4j
public final class BatchDispatcher {

    private final Map<String, EventApplier> byTopic;
    private final CollectEventJson json;
    private final Clock clock;

    public BatchDispatcher(List<EventApplier> appliers, CollectEventJson json, Clock clock) {
        Map<String, EventApplier> map = new LinkedHashMap<>();
        for (EventApplier applier : appliers) {
            map.put(applier.topic(), applier);
        }
        this.byTopic = Map.copyOf(map);
        this.json = json;
        this.clock = clock;
    }

    public DispatchResult dispatch(List<RawRecord> records) {
        if (records.isEmpty()) {
            return DispatchResult.NOTHING;
        }
        long writtenAtMs = Instant.now(clock).toEpochMilli();

        Map<String, List<CollectEvent>> byTopicEvents = new LinkedHashMap<>();
        List<Long> produce = new ArrayList<>(records.size());
        List<Long> consume = new ArrayList<>(records.size());
        int failed = 0;
        int ignored = 0;

        for (RawRecord record : records) {
            if (!byTopic.containsKey(record.topic())) {
                ignored++;
                continue;
            }
            CollectEvent event;
            try {
                event = json.read(record.value());
            } catch (RuntimeException e) {
                failed++;
                log.warn("이벤트를 못 읽었다 — 이 건만 버린다 ({}): {}", record.topic(), e.getMessage());
                continue;
            }
            byTopicEvents.computeIfAbsent(record.topic(), k -> new ArrayList<>()).add(event);
            if (event.ingestedAt() != null) {
                produce.add(record.timestampMs() - event.ingestedAt().toInstant().toEpochMilli());
            }
            consume.add(writtenAtMs - record.timestampMs());
        }

        ApplyResult applied = ApplyResult.NOTHING;
        for (Map.Entry<String, List<CollectEvent>> entry : byTopicEvents.entrySet()) {
            EventApplier applier = byTopic.get(entry.getKey());
            try {
                applied = applied.plus(applier.apply(entry.getValue()));
            } catch (RuntimeException e) {
                // 반영기가 터져도 다음 토픽은 계속한다. 컨슈머가 죽으면 그때부터 전부 밀린다.
                log.error("{} 반영 실패 — {}건을 버린다: {}", entry.getKey(), entry.getValue().size(), e.getMessage(), e);
                applied = applied.plus(new ApplyResult(0, entry.getValue().size(), 0));
            }
        }

        return new DispatchResult(applied, failed, ignored, LatencyStats.of(produce), LatencyStats.of(consume));
    }
}
