package com.ssafy.s15p21a104.collect;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.collect.http.SourceCallException;
import com.ssafy.s15p21a104.collect.publish.EventPublisher;
import com.ssafy.s15p21a104.collect.publish.PublishException;
import com.ssafy.s15p21a104.collect.source.PollResult;
import com.ssafy.s15p21a104.collect.source.SourceAdapter;
import java.time.Duration;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class SourcePollerTest {

    // KST 2026-09-14 09:00:00 — 07:30-13:00 창 안
    private static final Instant INSIDE = Instant.parse("2026-09-14T00:00:00Z");
    // KST 2026-09-14 14:00:00 — 창 밖
    private static final Instant OUTSIDE = Instant.parse("2026-09-14T05:00:00Z");

    private final MutableClock clock = new MutableClock(INSIDE);
    private final CallBudget budget = new CallBudget(1000, clock);
    private final RecordingPublisher publisher = new RecordingPublisher();

    private SourcePoller poller(SourceAdapter adapter) {
        return new SourcePoller(adapter, publisher, OperatingWindow.parse("07:30-13:00"), budget,
                Duration.ofSeconds(60), clock);
    }

    @Test
    void 창_안에서는_폴링하고_전송한다() {
        FakeAdapter adapter = FakeAdapter.returning(2);

        poller(adapter).tick();

        assertEquals(1, adapter.polls.size());
        assertEquals(OffsetDateTime.parse("2026-09-14T09:00:00+09:00"), adapter.polls.get(0), "poll_run_at 은 KST 초 단위");
        assertEquals(1, publisher.batches.size());
        assertEquals(2, publisher.batches.get(0).size());
        assertEquals("test.topic", publisher.topics.get(0));
    }

    @Test
    void 창_밖에서는_호출하지_않는다() {
        clock.set(OUTSIDE);
        FakeAdapter adapter = FakeAdapter.returning(2);

        poller(adapter).tick();

        assertTrue(adapter.polls.isEmpty());
        assertTrue(publisher.batches.isEmpty());
    }

    @Test
    @DisplayName("연속 3회 실패하면 60초 동안 건너뛰고, 지나면 다시 시도한다 (api-survey 4절 결정 5)")
    void 서킷_브레이커() {
        FakeAdapter adapter = FakeAdapter.failing();
        SourcePoller poller = poller(adapter);

        poller.tick();
        poller.tick();
        assertFalse(poller.isBreakerOpen(clock.instant()), "2회까지는 닫혀 있다");
        poller.tick();
        assertTrue(poller.isBreakerOpen(clock.instant()), "3회째 실패에 열린다");
        assertEquals(3, adapter.polls.size());

        clock.advance(Duration.ofSeconds(30));
        poller.tick();
        assertEquals(3, adapter.polls.size(), "OPEN 동안은 호출하지 않는다");

        clock.advance(Duration.ofSeconds(31));
        poller.tick();
        assertEquals(4, adapter.polls.size(), "60초가 지나면 다시 시도한다");
    }

    @Test
    void 성공하면_실패_횟수가_초기화된다() {
        FakeAdapter adapter = FakeAdapter.pattern(false, false, true, false, false);
        SourcePoller poller = poller(adapter);

        for (int i = 0; i < 5; i++) {
            poller.tick();
        }

        assertFalse(poller.isBreakerOpen(clock.instant()), "실패 2회 → 성공 → 실패 2회는 연속 3회가 아니다");
        assertEquals(5, adapter.polls.size());
    }

    @Test
    void 예산이_모자라면_호출하지_않는다() {
        CallBudget small = new CallBudget(5, clock);
        small.recordCall();
        small.recordCall();
        small.recordCall(); // 남은 2 < 회차당 3
        FakeAdapter adapter = FakeAdapter.returning(1);
        SourcePoller poller = new SourcePoller(adapter, publisher, OperatingWindow.ALL_DAY, small, Duration.ofSeconds(60),
                clock);

        poller.tick();

        assertTrue(adapter.polls.isEmpty());
    }

    @Test
    void 전송_실패는_브레이커에_세지_않고_다음_회차에_계속한다() {
        publisher.failWith = new PublishException("브로커 다운", 0, 2, new RuntimeException("timeout"));
        FakeAdapter adapter = FakeAdapter.returning(2);
        SourcePoller poller = poller(adapter);

        poller.tick();
        poller.tick();
        poller.tick();

        assertEquals(3, adapter.polls.size());
        assertFalse(poller.isBreakerOpen(clock.instant()));
    }

    @Test
    void 하루_계획_호출_수를_계산한다() {
        SourcePoller poller = poller(FakeAdapter.returning(0));

        // 330분 × 60 / 60초 = 330회차 × 3회 = 990
        assertEquals(990, poller.plannedCallsPerDay());
    }

    /** 폴링 결과·실패를 미리 정해 두는 가짜 어댑터. 회차당 호출 3회로 친다. */
    static final class FakeAdapter implements SourceAdapter {
        final List<OffsetDateTime> polls = new ArrayList<>();
        private final int events;
        private final boolean[] failures;

        private FakeAdapter(int events, boolean[] failures) {
            this.events = events;
            this.failures = failures;
        }

        static FakeAdapter returning(int events) {
            return new FakeAdapter(events, new boolean[0]);
        }

        static FakeAdapter failing() {
            return new FakeAdapter(0, new boolean[] {true});
        }

        /** 호출 순서대로 실패(true)/성공(false). 배열을 넘어가면 마지막 값을 반복한다. */
        static FakeAdapter pattern(boolean... failures) {
            return new FakeAdapter(1, failures);
        }

        @Override
        public String topic() {
            return "test.topic";
        }

        @Override
        public int callsPerRun() {
            return 3;
        }

        @Override
        public PollResult poll(OffsetDateTime pollRunAt) {
            int index = polls.size();
            polls.add(pollRunAt);
            if (failures.length > 0 && failures[Math.min(index, failures.length - 1)]) {
                throw SourceCallException.http("http://x/{KEY}", 503);
            }
            List<CollectEvent> list = new ArrayList<>();
            for (int i = 0; i < events; i++) {
                list.add(new CollectEvent("id" + i, "test.topic", "e" + i, null, pollRunAt, pollRunAt, Map.of("i", i)));
            }
            return new PollResult(list, 3);
        }
    }

    static final class RecordingPublisher implements EventPublisher {
        final List<String> topics = new ArrayList<>();
        final List<List<CollectEvent>> batches = new ArrayList<>();
        PublishException failWith;

        @Override
        public int publish(String topic, List<CollectEvent> events) {
            if (failWith != null) {
                throw failWith;
            }
            topics.add(topic);
            batches.add(events);
            return events.size();
        }
    }
}
