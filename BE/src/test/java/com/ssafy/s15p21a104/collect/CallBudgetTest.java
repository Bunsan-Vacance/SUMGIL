package com.ssafy.s15p21a104.collect;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class CallBudgetTest {

    // KST 2026-09-14 23:59:30
    private static final Instant NEAR_MIDNIGHT_KST = Instant.parse("2026-09-14T14:59:30Z");

    @Test
    void 호출을_세고_남은_예산을_안다() {
        CallBudget budget = new CallBudget(5, new MutableClock(NEAR_MIDNIGHT_KST));

        assertTrue(budget.canAfford(5));
        assertFalse(budget.canAfford(6));
        budget.recordCall();
        budget.recordCall();
        budget.recordCall();

        assertEquals(3, budget.used());
        assertEquals(2, budget.remaining());
        assertTrue(budget.canAfford(2));
        assertFalse(budget.canAfford(3));
    }

    @Test
    @DisplayName("날짜가 KST 기준으로 바뀌면 0부터 다시 센다")
    void KST_자정에_초기화된다() {
        MutableClock clock = new MutableClock(NEAR_MIDNIGHT_KST);
        CallBudget budget = new CallBudget(3, clock);
        budget.recordCall();
        budget.recordCall();
        budget.recordCall();
        assertFalse(budget.canAfford(1));

        clock.advance(Duration.ofSeconds(31)); // KST 00:00:01

        assertEquals(0, budget.used());
        assertEquals(3, budget.remaining());
        assertTrue(budget.canAfford(3));
    }

    @Test
    void UTC_자정은_경계가_아니다() {
        // UTC 2026-09-14 23:59:30 = KST 2026-09-15 08:59:30 → 30초 뒤에도 KST 같은 날
        MutableClock clock = new MutableClock(Instant.parse("2026-09-14T23:59:30Z"));
        CallBudget budget = new CallBudget(3, clock);
        budget.recordCall();

        clock.advance(Duration.ofSeconds(31));

        assertEquals(1, budget.used());
    }

    @Test
    void 예산은_1_이상이어야_한다() {
        assertThrows(IllegalArgumentException.class, () -> new CallBudget(0, new MutableClock(NEAR_MIDNIGHT_KST)));
    }
}
