package com.ssafy.s15p21a104.domain.buscongestion;

import com.ssafy.s15p21a104.collect.CallBudget;
import com.ssafy.s15p21a104.collect.http.HttpFetcher;
import com.ssafy.s15p21a104.global.cache.CacheKeys;
import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.RedisTemplate;
import tools.jackson.databind.json.JsonMapper;

/**
 * 정류소별 실시간 혼잡 등급 조회 (S15P21A104-297).
 *
 * <p>수집기처럼 배경에서 돌지 않는다. 정류소가 11,236곳인데 하루 예산이 1,000회라 전체 폴링은
 * 불가능하기 때문이다. 대신 <b>경로 검색이 버스 구간을 실제로 돌려줄 때만</b> 그 승차 정류소를
 * 불러온다({@link #prefetch}) — 지하철만 나온 경로는 한 번도 부르지 않는다.
 *
 * <p>호출은 {@link #prefetch} 에서만 일어나고 {@link #forStop} 은 캐시만 읽는다. 조회 경로에서
 * 외부를 부르면 응답 시간을 예측할 수 없기 때문이다. 정류소 하나를 부르면 <b>그 정류소에 서는
 * 모든 노선</b>이 한 번에 오므로 구간의 후보 노선 전부가 호출 한 번으로 채워진다.
 *
 * <p><b>어떤 실패도 밖으로 던지지 않는다.</b> 타임아웃·API 오류·예산 소진·캐시 손상 모두 빈 맵이
 * 되고 화면은 "정보 없음" 이 된다. 경로 검색이 이 값 때문에 깨지면 안 된다.
 */
@Slf4j
public class BusCongestionReader {

    static final String BASE_URL = "http://ws.bus.go.kr/api/rest/arrive/getLowArrInfoByStId";

    private final HttpFetcher fetcher;
    private final RedisTemplate<String, Object> redisTemplate;
    private final JsonMapper mapper;
    private final CallBudget budget;
    private final Clock clock;
    private final String serviceKey;
    private final Duration cacheTtl;
    private final Duration batchTimeout;

    public BusCongestionReader(HttpFetcher fetcher, RedisTemplate<String, Object> redisTemplate, JsonMapper mapper,
                               CallBudget budget, Clock clock, String serviceKey,
                               Duration cacheTtl, Duration batchTimeout) {
        this.fetcher = fetcher;
        this.redisTemplate = redisTemplate;
        this.mapper = mapper;
        this.budget = budget;
        this.clock = clock;
        this.serviceKey = serviceKey;
        this.cacheTtl = cacheTtl;
        this.batchTimeout = batchTimeout;
    }

    /**
     * 캐시에 없는 정류소를 병렬로 불러 캐시에 채운다. 전체 상한을 넘기면 못 받은 정류소는 그냥 둔다 —
     * 경로 검색 응답이 이 상한보다 더 늦어지지 않는다.
     *
     * @param stopIds 버스 구간의 승차 정류소 ID. null·빈 집합이면 아무것도 하지 않는다
     */
    public void prefetch(Set<String> stopIds) {
        if (stopIds == null || stopIds.isEmpty()) {
            return;
        }
        List<String> missing = new ArrayList<>();
        for (String stopId : stopIds) {
            if (stopId != null && !stopId.isBlank() && readCache(stopId) == null) {
                missing.add(stopId);
            }
        }
        if (missing.isEmpty()) {
            return;
        }
        List<CompletableFuture<Void>> futures = new ArrayList<>();
        for (String stopId : missing) {
            if (!budget.canAfford(1)) {
                log.warn("버스 혼잡도 하루 호출 예산 소진 — 정류소 {} 건너뜀 (사용 {}/{})",
                        stopId, budget.used(), budget.dailyLimit());
                continue;
            }
            budget.recordCall();
            futures.add(CompletableFuture.runAsync(() -> fetchInto(stopId)));
        }
        try {
            CompletableFuture.allOf(futures.toArray(CompletableFuture[]::new))
                    .get(batchTimeout.toMillis(), TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            log.warn("버스 혼잡도 수집 중단됨");
        } catch (Exception e) {
            // 상한 초과·개별 실패 — 받은 것만 쓴다
            log.warn("버스 혼잡도 {}곳 중 일부를 {}ms 안에 못 받았다: {}",
                    missing.size(), batchTimeout.toMillis(), e.getClass().getSimpleName());
        }
    }

    /**
     * @param stopId 승차 정류소 ID
     * @return 노선 ID → 다음 도착 버스. 캐시에 없으면 빈 맵. <b>외부를 부르지 않는다</b>
     */
    public Map<String, BusArrival> forStop(String stopId) {
        if (stopId == null || stopId.isBlank()) {
            return Map.of();
        }
        List<?> cached = readCache(stopId);
        if (cached == null) {
            return Map.of();
        }
        Map<String, BusArrival> out = new LinkedHashMap<>();
        for (Object item : cached) {
            if (!(item instanceof Map<?, ?> row)) {
                continue;
            }
            Object routeId = row.get("routeId");
            Object grade = row.get("grade");
            Object sec = row.get("arrivalSec");
            if (routeId == null || grade == null) {
                continue;
            }
            try {
                out.put(String.valueOf(routeId), new BusArrival(
                        String.valueOf(routeId),
                        BusCongestionGrade.valueOf(String.valueOf(grade)),
                        sec instanceof Number n ? n.intValue() : BusArrival.UNKNOWN_ARRIVAL_SEC));
            } catch (IllegalArgumentException e) {
                // 캐시에 모르는 등급 이름이 들어 있다 — 그 행만 버린다
                log.debug("버스 혼잡도 캐시 행을 읽지 못했다: {}", e.getMessage());
            }
        }
        return out;
    }

    private void fetchInto(String stopId) {
        try {
            Map<String, BusArrival> parsed = BusCongestionParser.parse(mapper, fetcher.get(uri(stopId)));
            writeCache(stopId, parsed);
        } catch (Exception e) {
            // 실패는 캐시에 넣지 않는다 — 넣으면 TTL 동안 "정보 없음" 이 굳는다
            log.warn("버스 혼잡도 정류소 {} 조회 실패: {}", stopId, e.getMessage());
        }
    }

    static URI uri(String stopId, String serviceKey) {
        return URI.create(BASE_URL
                + "?serviceKey=" + URLEncoder.encode(serviceKey, StandardCharsets.UTF_8)
                + "&stId=" + URLEncoder.encode(stopId, StandardCharsets.UTF_8)
                + "&resultType=json");
    }

    private URI uri(String stopId) {
        return uri(stopId, serviceKey);
    }

    /** 값 모양은 맵의 리스트다 — 타입 정보를 심지 않는 직렬화라 읽는 쪽이 모양을 안다. */
    private void writeCache(String stopId, Map<String, BusArrival> arrivals) {
        List<Map<String, Object>> rows = new ArrayList<>();
        for (BusArrival arrival : arrivals.values()) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("routeId", arrival.routeId());
            row.put("grade", arrival.grade().name());
            row.put("arrivalSec", arrival.arrivalSec());
            rows.add(row);
        }
        try {
            redisTemplate.opsForValue().set(CacheKeys.busCongestion(stopId), rows, cacheTtl);
        } catch (Exception e) {
            log.warn("버스 혼잡도 캐시 쓰기 실패 (정류소 {}): {}", stopId, e.getMessage());
        }
    }

    private List<?> readCache(String stopId) {
        try {
            Object raw = redisTemplate.opsForValue().get(CacheKeys.busCongestion(stopId));
            return raw instanceof List<?> list ? list : null;
        } catch (Exception e) {
            log.warn("버스 혼잡도 캐시 읽기 실패 (정류소 {}): {}", stopId, e.getMessage());
            return null;
        }
    }

    /** 오늘 쓴 호출 수 — 운영 로그·점검용. */
    public long usedCallsToday() {
        return budget.used();
    }

    /**
     * 항상 빈 값을 주는 리더. 인증키가 없거나 기능이 꺼졌을 때, 그리고 혼잡도와 무관한 테스트에서 쓴다.
     * 외부도 Redis 도 건드리지 않는다.
     */
    public static BusCongestionReader disabled() {
        return new BusCongestionReader(null, null, null, null, null, null, Duration.ZERO, Duration.ZERO) {
            @Override
            public void prefetch(Set<String> stopIds) {
                // 아무것도 하지 않는다
            }

            @Override
            public Map<String, BusArrival> forStop(String stopId) {
                return Map.of();
            }

            @Override
            public long usedCallsToday() {
                return 0;
            }
        };
    }
}
