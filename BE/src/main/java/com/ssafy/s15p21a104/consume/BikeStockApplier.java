package com.ssafy.s15p21a104.consume;

import com.ssafy.s15p21a104.collect.event.CollectEvent;
import com.ssafy.s15p21a104.global.cache.CacheKeys;
import java.time.Clock;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import lombok.extern.slf4j.Slf4j;

/**
 * {@code bike.stock} → Redis {@code bike:stock:{rental_id}} (S15P21A104-171).
 *
 * <p>따릉이 {@code stationId}(ST-xxx)는 우리 {@code bike_station.rental_id} 와 같은 체계라 대응표가 필요 없다.
 * 원천이 생성 시각을 주지 않으므로 신선도 기준은 {@code ingested_at} 이다 (kafka.md 5절).
 *
 * <p>멱등: 기존 값보다 <b>엄밀히 더 새로울 때만</b> 덮어쓴다(NFR-STREAM-004). 같은 시각이면 같은 회차의 중복이므로
 * 건너뛴다 — 페이지 경계에서 같은 행이 두 번 오는 것을 이것으로 흡수한다.
 *
 * <p>값이 깨진 행은 그 행만 건너뛴다. 배치 전체를 버리면 멀쩡한 대여소까지 재고를 잃는다.
 */
@Slf4j
public final class BikeStockApplier implements EventApplier {

    private final RedisWriter redis;
    private final Clock clock;

    public BikeStockApplier(RedisWriter redis, Clock clock) {
        this.redis = redis;
        this.clock = clock;
    }

    @Override
    public String topic() {
        return "bike.stock";
    }

    @Override
    public ApplyResult apply(List<CollectEvent> batch) {
        int written = 0;
        int skipped = 0;
        OffsetDateTime writtenAt = OffsetDateTime.now(clock.withZone(CollectEvent.KST));

        for (CollectEvent event : batch) {
            String rentalId = event.entityId();
            Integer available = number(event.payload().get("parkingBikeTotCnt"));
            Integer racks = number(event.payload().get("rackTotCnt"));
            if (rentalId == null || rentalId.isBlank() || available == null || event.ingestedAt() == null) {
                skipped++;
                continue;
            }

            String key = CacheKeys.bikeStock(rentalId);
            if (!isNewer(event.ingestedAt(), redis.get(key))) {
                skipped++;
                continue;
            }

            Map<String, Object> value = new LinkedHashMap<>();
            value.put("rental_id", rentalId);
            value.put("available", available);
            value.put("racks", racks);
            value.put("ingested_at", Times.format(event.ingestedAt()));
            value.put("written_at", Times.format(writtenAt));
            redis.set(key, value, CacheKeys.BIKE_STOCK_TTL);
            written++;
        }
        return new ApplyResult(written, skipped, 0);
    }

    /** 기존 값의 ingested_at 보다 엄밀히 새로우면 true. 기존 값이 없거나 시각을 못 읽으면 쓴다. */
    private static boolean isNewer(OffsetDateTime candidate, Optional<Map<String, Object>> stored) {
        OffsetDateTime previous = stored.map(v -> Times.parse(v.get("ingested_at"))).orElse(null);
        return previous == null || candidate.isAfter(previous);
    }

    /** 원천은 숫자도 문자열로 준다. 비었거나 숫자가 아니면 null — 읽는 쪽이 파싱하게 두지 않는다. */
    private static Integer number(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return Integer.valueOf(value.toString().trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
