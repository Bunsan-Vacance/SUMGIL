package com.ssafy.s15p21a104.collect;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.collect.publish.EventPublisher;
import com.ssafy.s15p21a104.collect.publish.PublishException;
import com.ssafy.s15p21a104.collect.source.PollResult;
import com.ssafy.s15p21a104.collect.source.SourceAdapter;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZonedDateTime;
import java.time.temporal.ChronoUnit;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;

/**
 * 소스 하나의 회차 실행기. 매 tick 마다 순서대로 본다:
 * 운영 시간 창 → 서킷 브레이커 → 하루 예산 → 폴링 → 전송 → 요약 로그.
 *
 * <p>서킷 브레이커는 "연속 3회 실패 시 60초 스킵"(api-survey 4절 결정 5, NFR-EXT-001). 한도 초과 응답 코드가
 * 확인되지 않아 정상 코드 외 응답은 전부 실패로 다룬다. 전송 실패는 외부 API 잘못이 아니라 브레이커에 세지 않는다.
 *
 * <p>스레드 안전: tick 은 동기화돼 있어 이전 회차가 끝나기 전에 다음 회차가 겹치지 않는다.
 */
@Slf4j
public final class SourcePoller {

    static final int FAILURE_THRESHOLD = 3;
    static final Duration OPEN_DURATION = Duration.ofSeconds(60);

    private final SourceAdapter adapter;
    private final EventPublisher publisher;
    private final OperatingWindow window;
    private final CallBudget budget;
    private final Duration interval;
    private final Clock clock;

    private int consecutiveFailures;
    private Instant openUntil;
    private Boolean lastInsideWindow;
    private boolean budgetWarned;

    public SourcePoller(SourceAdapter adapter, EventPublisher publisher, OperatingWindow window, CallBudget budget,
                        Duration interval, Clock clock) {
        this.adapter = adapter;
        this.publisher = publisher;
        this.window = window;
        this.budget = budget;
        this.interval = interval;
        this.clock = clock;
    }

    public String name() {
        return adapter.topic();
    }

    public Duration interval() {
        return interval;
    }

    public OperatingWindow window() {
        return window;
    }

    public CallBudget budget() {
        return budget;
    }

    public int callsPerRun() {
        return adapter.callsPerRun();
    }

    /** 하루 계획 호출 수 — 창 길이와 주기, 회차당 호출 수로 계산. 예산과 비교해 기동 시 경고한다. */
    public long plannedCallsPerDay() {
        long runs = window.minutesPerDay() * 60 / Math.max(1, interval.toSeconds());
        return runs * adapter.callsPerRun();
    }

    boolean isBreakerOpen(Instant now) {
        return openUntil != null && now.isBefore(openUntil);
    }

    /** 한 회차. 예외를 밖으로 내지 않는다 — 폴링은 실패해도 프로세스가 죽으면 안 된다. */
    public synchronized void tick() {
        Instant now = clock.instant();
        ZonedDateTime kst = now.atZone(CollectEvent.KST);

        boolean inside = window.contains(kst.toLocalTime());
        if (lastInsideWindow == null || lastInsideWindow != inside) {
            log.info("{} 운영 시간 창 {} — 지금 {} ({})", name(), window, inside ? "안" : "밖", kst.toLocalTime().truncatedTo(ChronoUnit.SECONDS));
            lastInsideWindow = inside;
        }
        if (!inside) {
            return;
        }
        if (isBreakerOpen(now)) {
            log.warn("{} 서킷 OPEN — {} 까지 건너뜀", name(), openUntil.atZone(CollectEvent.KST).toLocalTime().truncatedTo(ChronoUnit.SECONDS));
            return;
        }
        if (!budget.canAfford(adapter.callsPerRun())) {
            if (!budgetWarned) {
                log.warn("{} 하루 호출 예산 소진 ({}/{}) — 오늘은 더 호출하지 않는다", name(), budget.used(), budget.dailyLimit());
                budgetWarned = true;
            }
            return;
        }
        budgetWarned = false;

        OffsetDateTime pollRunAt = kst.toOffsetDateTime().truncatedTo(ChronoUnit.SECONDS);
        MDC.put("traceId", name() + "@" + pollRunAt.toLocalTime());
        long started = System.nanoTime();
        try {
            PollResult result = adapter.poll(pollRunAt);
            consecutiveFailures = 0;
            int sent = send(result);
            log.info("{} 회차 {} — 호출 {}회 · 행 {}건 · 전송 {}건 · {}ms · 오늘 호출 {}/{}", name(), pollRunAt, result.calls(),
                    result.events().size(), sent, elapsedMs(started), budget.used(), budget.dailyLimit());
        } catch (RuntimeException e) {
            consecutiveFailures++;
            log.warn("{} 회차 {} 실패 ({}회 연속): {}", name(), pollRunAt, consecutiveFailures, e.getMessage());
            if (consecutiveFailures >= FAILURE_THRESHOLD) {
                openUntil = now.plus(OPEN_DURATION);
                consecutiveFailures = 0;
                log.error("{} 연속 {}회 실패 — 서킷 OPEN, {}초 뒤 재시도", name(), FAILURE_THRESHOLD, OPEN_DURATION.toSeconds(), e);
            }
        } finally {
            MDC.remove("traceId");
        }
    }

    private int send(PollResult result) {
        try {
            return publisher.publish(adapter.topic(), result.events());
        } catch (PublishException e) {
            // 브로커 문제는 외부 API 브레이커와 무관하다. 다음 회차에 다시 시도한다.
            log.error("{} 전송 실패 — 성공 {}건 · 실패 {}건: {}", name(), e.sent(), e.failed(), e.getMessage(), e.getCause());
            return e.sent();
        }
    }

    private static long elapsedMs(long startedNanos) {
        return (System.nanoTime() - startedNanos) / 1_000_000;
    }
}
