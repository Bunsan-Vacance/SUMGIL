package com.ssafy.s15p21a104.domain.buscongestion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ssafy.s15p21a104.collect.CallBudget;
import com.ssafy.s15p21a104.collect.http.HttpFetcher;
import com.ssafy.s15p21a104.collect.http.SourceCallException;
import java.net.URI;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import tools.jackson.databind.json.JsonMapper;

/**
 * 정류소별 혼잡 등급 조회의 캐시·예산·실패 처리 (S15P21A104-297).
 *
 * <p>규칙은 하나다 — <b>무슨 일이 있어도 예외를 밖으로 던지지 않는다.</b> 경로 검색이 이 값
 * 때문에 깨지면 안 되기 때문이다. 못 구하면 빈 맵이고 화면은 "정보 없음" 이 된다.
 */
class BusCongestionReaderTest {

    private static final JsonMapper MAPPER = JsonMapper.builder().build();
    private static final Clock FIXED =
            Clock.fixed(Instant.parse("2026-09-21T09:45:00+09:00"), ZoneOffset.of("+09:00"));

    /** 정류소 하나에 노선 둘이 오는 응답. */
    private static String body(String routeId, int grade, int arrivalSec) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("busRouteId", routeId);
        row.put("reride_Num1", String.valueOf(grade));
        row.put("traTime1", String.valueOf(arrivalSec));
        row.put("arrmsg1", "곧 도착");
        Map<String, Object> msgBody = new LinkedHashMap<>();
        msgBody.put("itemList", List.of(row));
        return MAPPER.writeValueAsString(Map.of(
                "msgHeader", Map.of("headerCd", "0", "headerMsg", "정상"),
                "msgBody", msgBody));
    }

    /** 실제로 저장되는 값을 되돌려주는 Redis 흉내. 직렬화 왕복까지 보려고 맵 그대로 담는다. */
    private static final class FakeRedis {
        private final Map<String, Object> store = new HashMap<>();
        private final RedisTemplate<String, Object> template;
        private final AtomicInteger writes = new AtomicInteger();

        @SuppressWarnings("unchecked")
        FakeRedis() {
            template = mock(RedisTemplate.class);
            ValueOperations<String, Object> ops = mock(ValueOperations.class);
            lenient().when(template.opsForValue()).thenReturn(ops);
            lenient().when(ops.get(any())).thenAnswer(i -> store.get(i.getArgument(0, String.class)));
            lenient().doAnswer(i -> {
                store.put(i.getArgument(0, String.class), i.getArgument(1));
                writes.incrementAndGet();
                return null;
            }).when(ops).set(any(), any(), any(Duration.class));
        }
    }

    private static BusCongestionReader reader(FakeRedis redis, HttpFetcher fetcher, CallBudget budget) {
        return new BusCongestionReader(fetcher, redis.template, MAPPER, budget, FIXED,
                "TEST-KEY", Duration.ofSeconds(30), Duration.ofMillis(1500));
    }

    private static CallBudget budget(int limit) {
        return new CallBudget(limit, FIXED);
    }

    @Test
    @DisplayName("297-R1: 캐시가 비면 정류소당 1회 호출하고 결과를 캐시에 넣는다")
    void r1_캐시_미스() {
        FakeRedis redis = new FakeRedis();
        AtomicInteger calls = new AtomicInteger();
        HttpFetcher fetcher = uri -> {
            calls.incrementAndGet();
            return body("100100185", 4, 145);
        };
        BusCongestionReader reader = reader(redis, fetcher, budget(1000));

        reader.prefetch(Set.of("121000012"));
        Map<String, BusArrival> out = reader.forStop("121000012");

        assertEquals(1, calls.get(), "정류소 하나에 호출 한 번");
        assertEquals(BusCongestionGrade.NORMAL, out.get("100100185").grade());
        assertEquals(1, redis.writes.get(), "결과가 캐시에 들어가야 한다");
    }

    @Test
    @DisplayName("297-R2: 캐시가 있으면 호출하지 않는다")
    void r2_캐시_히트() {
        FakeRedis redis = new FakeRedis();
        AtomicInteger calls = new AtomicInteger();
        HttpFetcher fetcher = uri -> {
            calls.incrementAndGet();
            return body("100100185", 4, 145);
        };
        BusCongestionReader reader = reader(redis, fetcher, budget(1000));

        reader.prefetch(Set.of("121000012"));
        reader.prefetch(Set.of("121000012"));
        Map<String, BusArrival> out = reader.forStop("121000012");

        assertEquals(1, calls.get(), "둘째 조회는 캐시에서 나와야 한다");
        assertEquals(BusCongestionGrade.NORMAL, out.get("100100185").grade(), "캐시 왕복 후에도 값이 같아야 한다");
    }

    @Test
    @DisplayName("297-R3: 하루 예산을 넘기면 호출하지 않고 빈 맵을 준다")
    void r3_예산_소진() {
        FakeRedis redis = new FakeRedis();
        AtomicInteger calls = new AtomicInteger();
        HttpFetcher fetcher = uri -> {
            calls.incrementAndGet();
            return body("100100185", 4, 145);
        };
        CallBudget budget = budget(1);
        BusCongestionReader reader = reader(redis, fetcher, budget);

        reader.prefetch(Set.of("A"));
        reader.prefetch(Set.of("B"));

        assertEquals(1, calls.get(), "예산 1회면 둘째 정류소는 호출하지 않는다");
        assertTrue(reader.forStop("B").isEmpty());
    }

    @Test
    @DisplayName("297-R4: 외부 호출이 실패해도 예외가 새지 않고 빈 맵이다")
    void r4_호출_실패() {
        FakeRedis redis = new FakeRedis();
        HttpFetcher fetcher = uri -> {
            throw SourceCallException.timeout("http://ws.bus.go.kr/{KEY}", new RuntimeException("timeout"));
        };
        BusCongestionReader reader = reader(redis, fetcher, budget(1000));

        reader.prefetch(Set.of("121000012"));

        assertTrue(reader.forStop("121000012").isEmpty());
        assertEquals(0, redis.writes.get(), "실패를 캐시에 넣어 30초간 굳히지 않는다");
    }

    @Test
    @DisplayName("297-R5: 응답이 깨져도 빈 맵이다")
    void r5_응답_깨짐() {
        FakeRedis redis = new FakeRedis();
        HttpFetcher fetcher = uri -> "<html>error</html>";
        BusCongestionReader reader = reader(redis, fetcher, budget(1000));

        reader.prefetch(Set.of("121000012"));

        assertTrue(reader.forStop("121000012").isEmpty());
    }

    @Test
    @DisplayName("297-R6: prefetch 하지 않은 정류소는 호출 없이 빈 맵 — 조회 경로에서 외부를 부르지 않는다")
    void r6_prefetch_안한_정류소() {
        FakeRedis redis = new FakeRedis();
        AtomicInteger calls = new AtomicInteger();
        HttpFetcher fetcher = uri -> {
            calls.incrementAndGet();
            return body("100100185", 4, 145);
        };
        BusCongestionReader reader = reader(redis, fetcher, budget(1000));

        assertTrue(reader.forStop("121000012").isEmpty());
        assertEquals(0, calls.get(), "forStop 은 캐시만 읽는다");
    }

    @Test
    @DisplayName("297-R7: 정류소 여러 곳을 한 번에 — 각각 한 번씩만 부른다")
    void r7_여러_정류소() {
        FakeRedis redis = new FakeRedis();
        Map<String, Integer> perStop = new java.util.concurrent.ConcurrentHashMap<>();
        HttpFetcher fetcher = uri -> {
            String stId = uri.getQuery().replaceAll(".*stId=([^&]+).*", "$1");
            perStop.merge(stId, 1, Integer::sum);
            return body("R" + stId, 3, 100);
        };
        BusCongestionReader reader = reader(redis, fetcher, budget(1000));

        reader.prefetch(Set.of("A", "B", "C"));

        assertEquals(Map.of("A", 1, "B", 1, "C", 1), perStop);
        assertEquals(BusCongestionGrade.RELAXED, reader.forStop("B").get("RB").grade());
    }

    @Test
    @DisplayName("297-R8: 빈 정류소 집합이면 아무것도 하지 않는다")
    void r8_빈_집합() {
        FakeRedis redis = new FakeRedis();
        AtomicInteger calls = new AtomicInteger();
        HttpFetcher fetcher = uri -> {
            calls.incrementAndGet();
            return body("X", 3, 10);
        };
        BusCongestionReader reader = reader(redis, fetcher, budget(1000));

        reader.prefetch(Set.of());
        reader.prefetch(null);

        assertEquals(0, calls.get());
    }

    @Test
    @DisplayName("297-R9: 요청 URL 에 정류소와 인증키가 들어간다")
    void r9_요청_URL() {
        FakeRedis redis = new FakeRedis();
        java.util.concurrent.atomic.AtomicReference<URI> seen = new java.util.concurrent.atomic.AtomicReference<>();
        HttpFetcher fetcher = uri -> {
            seen.set(uri);
            return body("X", 3, 10);
        };
        BusCongestionReader reader = reader(redis, fetcher, budget(1000));

        reader.prefetch(Set.of("121000012"));

        URI uri = seen.get();
        assertNotNull(uri);
        assertTrue(uri.toString().contains("getLowArrInfoByStId"), uri.toString());
        assertTrue(uri.getQuery().contains("stId=121000012"), uri.getQuery());
        assertTrue(uri.getQuery().contains("serviceKey=TEST-KEY"), "인증키가 실려야 한다");
        assertTrue(uri.getQuery().contains("resultType=json"), uri.getQuery());
    }

    @Test
    @DisplayName("297-R10: 캐시에 쓰레기가 들어 있어도 예외 없이 빈 맵이다")
    void r10_캐시_형식_깨짐() {
        FakeRedis redis = new FakeRedis();
        redis.store.put("bus:congestion:121000012", "쓰레기");
        HttpFetcher fetcher = uri -> body("X", 3, 10);
        BusCongestionReader reader = reader(redis, fetcher, budget(1000));

        assertTrue(reader.forStop("121000012").isEmpty());
    }

    @Test
    @DisplayName("297-R11(2026-09-22 부하테스트 트러블슈팅): 정류소가 많아도 동시 조회 스레드 수가 상한을 넘지 않는다")
    void r11_동시_조회_스레드_상한() throws Exception {
        FakeRedis redis = new FakeRedis();
        int stopCount = 40; // 스레드 풀 상한(16)보다 훨씬 많게
        AtomicInteger concurrent = new AtomicInteger();
        AtomicInteger peakConcurrent = new AtomicInteger();
        Set<String> seenThreadNames = java.util.concurrent.ConcurrentHashMap.newKeySet();
        HttpFetcher fetcher = uri -> {
            seenThreadNames.add(Thread.currentThread().getName());
            int now = concurrent.incrementAndGet();
            peakConcurrent.updateAndGet(prev -> Math.max(prev, now));
            try {
                Thread.sleep(50); // 겹치는 구간을 강제로 만든다
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            } finally {
                concurrent.decrementAndGet();
            }
            return body("X", 3, 10);
        };
        Set<String> stopIds = new java.util.HashSet<>();
        for (int i = 0; i < stopCount; i++) {
            stopIds.add("STOP-" + i);
        }
        BusCongestionReader reader = new BusCongestionReader(fetcher, redis.template, MAPPER, budget(1000),
                FIXED, "TEST-KEY", Duration.ofSeconds(30), Duration.ofSeconds(5));

        reader.prefetch(stopIds);

        assertTrue(peakConcurrent.get() <= 16,
                "동시 조회 스레드 수는 풀 상한(16)을 넘으면 안 된다 — 실측 " + peakConcurrent.get());
        assertTrue(seenThreadNames.stream().allMatch(name -> name.startsWith("bus-congestion-fetch-")),
                "전용 스레드 풀 이름 규칙을 따라야 한다: " + seenThreadNames);
    }
}
