package com.ssafy.s15p21a104.domain.bike.stock;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.Mockito.when;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

/**
 * bike:stock:{rentalId} 캐시 판독(BIKE-001 156). AVAILABLE/STALE/UNAVAILABLE 세 상태와
 * 값이 없거나 깨진 경우를 다룬다 — 신선도 창은 180초(CacheKeys.BIKE_STOCK_FRESH_WINDOW).
 */
@ExtendWith(MockitoExtension.class)
class BikeStockReaderTest {

    private static final Instant NOW = Instant.parse("2026-09-17T01:00:00Z");

    @Mock
    private RedisTemplate<String, Object> redisTemplate;

    @Mock
    private ValueOperations<String, Object> valueOperations;

    private BikeStockReader reader;

    private void given(Map<String, Object> value) {
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(valueOperations.get("bike:stock:ST-1")).thenReturn(value);
        reader = new BikeStockReader(redisTemplate, Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @Test
    @DisplayName("신선도 창(180초) 이내면 AVAILABLE")
    void 신선하면_AVAILABLE() {
        given(rawValue(7, NOW.minusSeconds(60)));

        BikeStock stock = reader.find("ST-1");

        assertEquals(7, stock.available());
        assertEquals(BikeStockStatus.AVAILABLE, stock.status());
    }

    @Test
    @DisplayName("신선도 창을 넘겼지만 캐시는 있으면 STALE — 마지막 값을 그대로 준다")
    void 오래됐으면_STALE() {
        given(rawValue(3, NOW.minusSeconds(200)));

        BikeStock stock = reader.find("ST-1");

        assertEquals(3, stock.available());
        assertEquals(BikeStockStatus.STALE, stock.status());
    }

    @Test
    @DisplayName("캐시가 아예 없으면 UNAVAILABLE — 값은 null")
    void 캐시없으면_UNAVAILABLE() {
        given(null);

        BikeStock stock = reader.find("ST-1");

        assertNull(stock.available());
        assertNull(stock.updatedAt());
        assertEquals(BikeStockStatus.UNAVAILABLE, stock.status());
    }

    @Test
    @DisplayName("값이 숫자로 안 읽히면 지어내지 않고 UNAVAILABLE")
    void 값이_깨졌으면_UNAVAILABLE() {
        Map<String, Object> broken = new LinkedHashMap<>();
        broken.put("available", "not-a-number");
        broken.put("ingested_at", NOW.toString());
        given(broken);

        BikeStock stock = reader.find("ST-1");

        assertEquals(BikeStockStatus.UNAVAILABLE, stock.status());
    }

    private static Map<String, Object> rawValue(int available, Instant ingestedAt) {
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("available", available);
        value.put("ingested_at", ingestedAt.atOffset(ZoneOffset.UTC).format(DateTimeFormatter.ISO_OFFSET_DATE_TIME));
        return value;
    }
}
