package com.ssafy.s15p21a104.domain.bike.stock;

import com.ssafy.s15p21a104.global.cache.CacheKeys;
import java.time.Clock;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.Map;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Component;

/**
 * {@code bike:stock:{rentalId}} 캐시를 읽어 신선도를 판정한다(BIKE-001 156). 값 모양은 반영기
 * ({@code consume.BikeStockApplier})가 쓰는 것과 같다 — {@code available}·{@code racks}·{@code ingested_at}.
 *
 * <p>서버는 이 캐시를 읽기만 한다. 값이 없거나 형식이 깨졌으면 예외를 던지지 않고 UNAVAILABLE로 다룬다 —
 * 재고를 모르는 상태는 에러가 아니다(원칙: 값을 지어내지 않는다).
 */
@Component
public class BikeStockReader {

    private static final DateTimeFormatter ISO = DateTimeFormatter.ISO_OFFSET_DATE_TIME;

    private final RedisTemplate<String, Object> redisTemplate;
    private final Clock clock;

    public BikeStockReader(RedisTemplate<String, Object> redisTemplate, Clock clock) {
        this.redisTemplate = redisTemplate;
        this.clock = clock;
    }

    public BikeStock find(String rentalId) {
        Object raw = redisTemplate.opsForValue().get(CacheKeys.bikeStock(rentalId));
        if (!(raw instanceof Map<?, ?> map)) {
            return BikeStock.unavailable();
        }
        Integer available = asInt(map.get("available"));
        if (available == null || available < 0) {
            return BikeStock.unavailable();
        }
        Integer rackCount = asNonNegativeInt(map.get("racks"));
        OffsetDateTime updatedAt = asTime(map.get("ingested_at"));
        if (updatedAt == null) {
            return BikeStock.unavailable();
        }
        boolean fresh = Duration.between(updatedAt, OffsetDateTime.now(clock))
                .compareTo(CacheKeys.BIKE_STOCK_FRESH_WINDOW) <= 0;
        return new BikeStock(available, rackCount, updatedAt,
                fresh ? BikeStockStatus.AVAILABLE : BikeStockStatus.STALE);
    }

    private static Integer asInt(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return Integer.valueOf(value.toString().trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static Integer asNonNegativeInt(Object value) {
        Integer parsed = asInt(value);
        return parsed == null || parsed < 0 ? null : parsed;
    }

    private static OffsetDateTime asTime(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return OffsetDateTime.parse(value.toString(), ISO);
        } catch (DateTimeParseException e) {
            return null;
        }
    }
}
