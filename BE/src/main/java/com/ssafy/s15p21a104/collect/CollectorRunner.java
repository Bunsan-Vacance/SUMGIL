package com.ssafy.s15p21a104.collect;

import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;

/**
 * 수집기 진입점 (S15P21A104-169). 실행:
 * <pre>
 *   SPRING_PROFILES_ACTIVE=local,collect ./gradlew bootRun                       # 주기 실행
 *   SPRING_PROFILES_ACTIVE=local,collect ./gradlew bootRun --args='--collect.run-once=true --collect.dry-run=true'
 * </pre>
 * 주기 실행은 소스별 fixed-delay 로 돈다 — 회차가 오래 걸려도 다음 회차가 겹치거나 몰리지 않아 하루 호출 수가 계획을 넘지 않는다.
 * 스케줄러 스레드가 살아 있어 JVM 이 내려가지 않는다. run-once 는 활성 소스를 한 회차씩 순서대로 돌리고 끝난다.
 */
@Slf4j
public class CollectorRunner implements ApplicationRunner {

    private final CollectProperties props;
    private final CollectPlan plan;
    private final ThreadPoolTaskScheduler scheduler;

    public CollectorRunner(CollectProperties props, CollectPlan plan, ThreadPoolTaskScheduler scheduler) {
        this.props = props;
        this.plan = plan;
        this.scheduler = scheduler;
    }

    @Override
    public void run(ApplicationArguments args) {
        if (plan.pollers().isEmpty()) {
            log.warn("활성 소스가 없다 — collect.*.enabled 와 인증키(SEOUL_SUBWAY_KEY·SEOUL_API_KEY·KMA_API_KEY)를 확인한다");
            return;
        }
        for (SourcePoller poller : plan.pollers()) {
            long planned = poller.plannedCallsPerDay();
            int limit = poller.budget().dailyLimit();
            log.info("{} — 주기 {}s · 창 {} · 회차당 {}회 · 하루 계획 {}회 / 예산 {}회{}", poller.name(),
                    poller.interval().toSeconds(), poller.window(), poller.callsPerRun(), planned, limit,
                    planned > limit ? " ⚠ 계획이 예산을 넘는다 — 창을 줄이거나 주기를 늘려야 한다" : "");
        }
        if (props.dryRun()) {
            log.info("dry-run — Kafka 에 보내지 않고 로그만 남긴다");
        }

        if (props.runOnce()) {
            log.info("run-once — 활성 소스 {}개를 한 회차씩 돌리고 끝낸다", plan.pollers().size());
            for (SourcePoller poller : plan.pollers()) {
                poller.tick();
            }
            log.info("run-once 종료");
            return;
        }

        for (SourcePoller poller : plan.pollers()) {
            scheduler.scheduleWithFixedDelay(poller::tick, poller.interval());
        }
        log.info("수집기 시작 — 소스 {}개 주기 실행 중 (종료: Ctrl+C)", plan.pollers().size());
    }
}
