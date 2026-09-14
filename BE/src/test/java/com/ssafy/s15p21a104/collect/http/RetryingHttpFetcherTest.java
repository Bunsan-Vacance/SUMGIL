package com.ssafy.s15p21a104.collect.http;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.net.URI;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class RetryingHttpFetcherTest {

    private static final URI URL = URI.create("http://example.test/x");

    private final List<Duration> slept = new ArrayList<>();
    private final AtomicInteger attempts = new AtomicInteger();

    private RetryingHttpFetcher fetcher(HttpFetcher delegate) {
        return new RetryingHttpFetcher(delegate, 2, Duration.ofMillis(500), slept::add, attempts::incrementAndGet);
    }

    @Test
    @DisplayName("타임아웃은 지수 백오프로 최대 2회 재시도하고, 시도마다 예산을 센다")
    void 타임아웃은_재시도한다() {
        AtomicInteger calls = new AtomicInteger();
        HttpFetcher flaky = uri -> {
            if (calls.incrementAndGet() < 3) {
                throw SourceCallException.timeout("url", new RuntimeException("slow"));
            }
            return "ok";
        };

        assertEquals("ok", fetcher(flaky).get(URL));
        assertEquals(3, attempts.get());
        assertEquals(List.of(Duration.ofMillis(500), Duration.ofMillis(1000)), slept);
    }

    @Test
    void 재시도를_다_써도_실패면_마지막_예외를_던진다() {
        HttpFetcher down = uri -> {
            throw SourceCallException.http("url", 503);
        };

        SourceCallException e = assertThrows(SourceCallException.class, () -> fetcher(down).get(URL));

        assertEquals(SourceCallException.Kind.HTTP_5XX, e.kind());
        assertEquals(3, attempts.get(), "첫 시도 + 재시도 2회");
    }

    @Test
    void 클라이언트_오류_4xx_는_재시도하지_않는다() {
        HttpFetcher rejected = uri -> {
            throw SourceCallException.http("url", 401);
        };

        SourceCallException e = assertThrows(SourceCallException.class, () -> fetcher(rejected).get(URL));

        assertEquals(SourceCallException.Kind.HTTP_4XX, e.kind());
        assertEquals(1, attempts.get());
        assertEquals(List.of(), slept);
    }

    @Test
    void API_오류_코드는_재시도하지_않는다() {
        HttpFetcher apiError = uri -> {
            throw SourceCallException.apiError("bike.stock", "ERROR-336", "1000건 초과");
        };

        assertThrows(SourceCallException.class, () -> fetcher(apiError).get(URL));
        assertEquals(1, attempts.get());
    }

    @Test
    void 인증키는_메시지에서_가린다() {
        assertEquals("http://h/{KEY}/json/bikeList/1/1000/",
                JdkHttpFetcher.redact("http://h/abc123/json/bikeList/1/1000/", "abc123"));
        assertEquals("https://h/x?authKey={KEY}&nx=60",
                JdkHttpFetcher.redact("https://h/x?authKey=a%2Fb%3D&nx=60", "a/b="));
    }
}
