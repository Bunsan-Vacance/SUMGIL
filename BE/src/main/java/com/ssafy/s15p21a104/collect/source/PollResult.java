package com.ssafy.s15p21a104.collect.source;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import java.util.List;

/**
 * 한 회차의 결과.
 *
 * @param events 이벤트 목록 (행 1개 = 이벤트 1건)
 * @param calls  실제로 보낸 요청 수 (재시도 제외 — 재시도는 HttpFetcher 가 예산에 직접 센다)
 */
public record PollResult(List<CollectEvent> events, int calls) {

    public PollResult {
        events = List.copyOf(events);
    }

    public static PollResult empty(int calls) {
        return new PollResult(List.of(), calls);
    }
}
