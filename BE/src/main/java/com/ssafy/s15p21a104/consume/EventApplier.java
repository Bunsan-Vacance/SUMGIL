package com.ssafy.s15p21a104.consume;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import java.util.List;

/**
 * 토픽 하나의 이벤트를 Redis 에 반영한다 (S15P21A104-171).
 *
 * <p>배치로 받는다 — Kafka 배치 리스너가 한 번에 여러 건을 주고, 지하철은 한 회차가 약 3,000건이라 건별로 쓰면 왕복이 너무 많다.
 * 한 배치가 회차 하나와 일치한다는 보장은 없다 (max.poll.records 로 잘린다). 그래서 반영기는 배치 경계에 기대지 않고,
 * 언제 잘려 들어와도 같은 결과가 나오게 쓴다.
 */
public interface EventApplier {

    /** 이 반영기가 맡는 토픽. {@code CollectEvent.source} 와 같다 */
    String topic();

    /** 예외를 밖으로 내지 않는다 — 한 배치가 실패해도 컨슈머가 죽으면 안 된다. 실패는 결과의 skipped 로 센다 */
    ApplyResult apply(List<CollectEvent> batch);
}
