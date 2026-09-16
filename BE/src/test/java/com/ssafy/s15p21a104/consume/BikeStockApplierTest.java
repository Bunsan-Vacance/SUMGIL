package com.ssafy.s15p21a104.consume;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.global.cache.CacheKeys;
import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 따릉이 재고 반영 (S15P21A104-171). 따릉이 stationId 는 우리 rental_id 와 같은 체계라 매핑이 없다.
 * 원천이 생성 시각을 주지 않으므로 신선도 기준은 ingested_at 이다 (kafka.md 5절).
 */
class BikeStockApplierTest {

    /** KST 2026-09-16 10:30:20 */
    private static final Clock CLOCK = Clock.fixed(Instant.parse("2026-09-16T01:30:20Z"), ZoneOffset.UTC);

    private final InMemoryRedisWriter redis = new InMemoryRedisWriter();
    private final BikeStockApplier applier = new BikeStockApplier(redis, CLOCK);

    private static CollectEvent event(String rentalId, int available, int racks, String ingestedAt) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("stationId", rentalId);
        row.put("parkingBikeTotCnt", String.valueOf(available));
        row.put("rackTotCnt", String.valueOf(racks));
        row.put("stationName", rentalId + ". 대여소");
        OffsetDateTime at = OffsetDateTime.parse(ingestedAt);
        return new CollectEvent("id-" + rentalId + "-" + ingestedAt, "bike.stock", rentalId, null, at, at, row);
    }

    @Test
    @DisplayName("재고를 bike:stock:{rental_id} 에 쓴다")
    void 쓴다() {
        ApplyResult result = applier.apply(List.of(event("ST-1577", 6, 15, "2026-09-16T10:30:12+09:00")));

        assertEquals(new ApplyResult(1, 0, 0), result);
        Map<String, Object> value = redis.get(CacheKeys.bikeStock("ST-1577")).orElseThrow();
        assertEquals("ST-1577", value.get("rental_id"));
        assertEquals(6, value.get("available"), "숫자로 쓴다 — 원천은 문자열이지만 읽는 쪽이 파싱하게 두지 않는다");
        assertEquals(15, value.get("racks"));
        assertEquals("2026-09-16T10:30:12+09:00", value.get("ingested_at"));
        assertEquals("2026-09-16T10:30:20+09:00", value.get("written_at"), "written_at 은 우리가 쓴 시각(KST)");
        assertEquals(CacheKeys.BIKE_STOCK_TTL, redis.ttls.get(CacheKeys.bikeStock("ST-1577")));
    }

    @Test
    @DisplayName("오래된 이벤트는 최신 값을 덮지 않는다 (NFR-STREAM-004)")
    void 오래된_이벤트는_안_덮는다() {
        applier.apply(List.of(event("ST-1577", 6, 15, "2026-09-16T10:30:12+09:00")));

        ApplyResult result = applier.apply(List.of(event("ST-1577", 99, 15, "2026-09-16T10:28:12+09:00")));

        assertEquals(new ApplyResult(0, 1, 0), result);
        assertEquals(6, redis.get(CacheKeys.bikeStock("ST-1577")).orElseThrow().get("available"),
                "옛 값이 덮지 못했다");
    }

    @Test
    @DisplayName("같은 회차가 두 번 와도 한 번만 쓴다 — 페이지 경계 중복")
    void 중복은_한_번만() {
        CollectEvent same = event("ST-1577", 6, 15, "2026-09-16T10:30:12+09:00");

        applier.apply(List.of(same));
        int writesAfterFirst = redis.writes;
        ApplyResult result = applier.apply(List.of(same));

        assertEquals(new ApplyResult(0, 1, 0), result);
        assertEquals(writesAfterFirst, redis.writes, "두 번째는 Redis 를 건드리지 않는다");
    }

    @Test
    @DisplayName("더 새로운 이벤트는 덮어쓴다")
    void 새_이벤트는_덮는다() {
        applier.apply(List.of(event("ST-1577", 6, 15, "2026-09-16T10:30:12+09:00")));

        ApplyResult result = applier.apply(List.of(event("ST-1577", 3, 15, "2026-09-16T10:32:12+09:00")));

        assertEquals(new ApplyResult(1, 0, 0), result);
        assertEquals(3, redis.get(CacheKeys.bikeStock("ST-1577")).orElseThrow().get("available"));
    }

    @Test
    @DisplayName("한 배치에 여러 대여소가 있으면 각각 쓴다")
    void 여러_대여소() {
        ApplyResult result = applier.apply(List.of(
                event("ST-1", 1, 10, "2026-09-16T10:30:12+09:00"),
                event("ST-2", 2, 10, "2026-09-16T10:30:12+09:00"),
                event("ST-3", 3, 10, "2026-09-16T10:30:12+09:00")));

        assertEquals(new ApplyResult(3, 0, 0), result);
        assertEquals(3, redis.values.size());
    }

    @Test
    @DisplayName("재고 숫자가 비었거나 숫자가 아니면 그 행만 건너뛴다 — 배치 전체를 버리지 않는다")
    void 이상한_행은_그_행만_건너뛴다() {
        Map<String, Object> broken = new LinkedHashMap<>();
        broken.put("stationId", "ST-BAD");
        broken.put("parkingBikeTotCnt", "");
        broken.put("rackTotCnt", "10");
        OffsetDateTime at = OffsetDateTime.parse("2026-09-16T10:30:12+09:00");
        CollectEvent bad = new CollectEvent("id-bad", "bike.stock", "ST-BAD", null, at, at, broken);

        ApplyResult result = applier.apply(List.of(bad, event("ST-OK", 5, 10, "2026-09-16T10:30:12+09:00")));

        assertEquals(1, result.written(), "정상 행은 쓴다");
        assertEquals(1, result.skipped(), "이상한 행은 건너뛴 것으로 센다");
        assertTrue(redis.get(CacheKeys.bikeStock("ST-BAD")).isEmpty());
    }

    @Test
    void 빈_배치는_아무것도_안_한다() {
        assertEquals(new ApplyResult(0, 0, 0), applier.apply(List.of()));
        assertEquals(0, redis.writes);
    }
}
