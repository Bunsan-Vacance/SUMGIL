package com.ssafy.s15p21a104.collect.http;

import java.net.URI;
import java.time.Duration;
import lombok.extern.slf4j.Slf4j;

/**
 * 재시도 규칙 (NFR-EXT-002): 타임아웃·5xx 만 최대 N회, 지수 백오프. 4xx 는 재시도하지 않는다.
 * 시도마다 {@code onAttempt} 를 부른다 — 하루 호출 예산은 재시도까지 전부 센다 ({@code CallBudget}).
 */
@Slf4j
public final class RetryingHttpFetcher implements HttpFetcher {

    /** 테스트에서 실제로 기다리지 않게 바꿔 끼우는 대기 함수. */
    @FunctionalInterface
    public interface Sleeper {
        void sleep(Duration duration) throws InterruptedException;
    }

    public static final Sleeper THREAD_SLEEP = duration -> Thread.sleep(duration.toMillis());

    private final HttpFetcher delegate;
    private final int maxRetries;
    private final Duration firstBackoff;
    private final Sleeper sleeper;
    private final Runnable onAttempt;

    public RetryingHttpFetcher(HttpFetcher delegate, int maxRetries, Duration firstBackoff, Sleeper sleeper,
                               Runnable onAttempt) {
        this.delegate = delegate;
        this.maxRetries = Math.max(0, maxRetries);
        this.firstBackoff = firstBackoff;
        this.sleeper = sleeper;
        this.onAttempt = onAttempt;
    }

    @Override
    public String get(URI uri) {
        Duration backoff = firstBackoff;
        for (int attempt = 0; ; attempt++) {
            onAttempt.run();
            try {
                return delegate.get(uri);
            } catch (SourceCallException e) {
                if (!e.retryable() || attempt >= maxRetries) {
                    throw e;
                }
                log.warn("외부 호출 실패({}), {}ms 뒤 재시도 {}/{}: {}", e.kind(), backoff.toMillis(), attempt + 1,
                        maxRetries, e.getMessage());
                try {
                    sleeper.sleep(backoff);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    throw e;
                }
                backoff = backoff.multipliedBy(2);
            }
        }
    }
}
