package com.ssafy.s15p21a104.collect;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import java.time.Clock;
import java.time.LocalDate;

/**
 * 소스별 하루 호출 예산 (S15P21A104-170). 열린데이터광장 키는 하루 1,000회가 한도인데
 * 한도 초과 시 응답 코드가 확인되지 않아, 서버가 끊기 전에 우리가 먼저 멈춘다.
 *
 * <p>날짜는 KST 기준으로 바뀌며, 재시도 한 번도 호출 한 번으로 센다 — 실제 호출보다 적게 세는 일은 없게 한다.
 * 프로세스가 재시작되면 0 부터 다시 센다(창을 보수적으로 잡아 그 안에서는 문제가 없고, 영속화는 과하다).
 */
public final class CallBudget {

    private final int dailyLimit;
    private final Clock clock;
    private LocalDate day;
    private long used;

    public CallBudget(int dailyLimit, Clock clock) {
        if (dailyLimit <= 0) {
            throw new IllegalArgumentException("하루 호출 예산은 1 이상이어야 한다: " + dailyLimit);
        }
        this.dailyLimit = dailyLimit;
        this.clock = clock;
        this.day = today();
    }

    public synchronized void recordCall() {
        rollover();
        used++;
    }

    public synchronized long used() {
        rollover();
        return used;
    }

    public synchronized long remaining() {
        rollover();
        return Math.max(0, dailyLimit - used);
    }

    public synchronized boolean canAfford(int calls) {
        rollover();
        return used + calls <= dailyLimit;
    }

    public int dailyLimit() {
        return dailyLimit;
    }

    private void rollover() {
        LocalDate now = today();
        if (!now.equals(day)) {
            day = now;
            used = 0;
        }
    }

    private LocalDate today() {
        return LocalDate.now(clock.withZone(CollectEvent.KST));
    }
}
