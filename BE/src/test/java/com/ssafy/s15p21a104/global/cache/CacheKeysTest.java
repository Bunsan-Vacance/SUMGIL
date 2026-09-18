package com.ssafy.s15p21a104.global.cache;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Duration;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/** 키 형식과 TTL 정책을 못 박는다. 근거는 BE/docs/cache/strategy.md · BE/docs/infra/consumer.md. */
class CacheKeysTest {

    @Test
    void 키_형식() {
        assertEquals("bike:stock:ST-1577", CacheKeys.bikeStock("ST-1577"));
        assertEquals("subway:arrival:222", CacheKeys.subwayArrival("222"));
        assertEquals("subway:arrival:status", CacheKeys.SUBWAY_ARRIVAL_STATUS);
        assertEquals("reversal:222:221:0:14", CacheKeys.reversal("222", "221", 0, 14));
    }

    @Test
    @DisplayName("TTL 은 수집 주기보다 길다 — 짧으면 수집이 멀쩡해도 주기마다 키가 사라진다")
    void TTL_은_수집_주기보다_길다() {
        // 수집 주기: 따릉이 120초 · 지하철 60초 (BE/k8s/prod/be-config.env, S15P21A104-170)
        Duration bikeInterval = Duration.ofSeconds(120);
        Duration subwayInterval = Duration.ofSeconds(60);

        assertTrue(CacheKeys.BIKE_STOCK_TTL.compareTo(bikeInterval) > 0,
                "따릉이 TTL %s 이 수집 주기 %s 보다 짧다".formatted(CacheKeys.BIKE_STOCK_TTL, bikeInterval));
        assertTrue(CacheKeys.SUBWAY_ARRIVAL_TTL.compareTo(subwayInterval) > 0,
                "지하철 TTL %s 이 수집 주기 %s 보다 짧다".formatted(CacheKeys.SUBWAY_ARRIVAL_TTL, subwayInterval));

        // 한 회차를 놓치고 서킷 브레이커(60초)까지 겹쳐도 버틴다. 두 회차 연속 놓치면 만료돼 "모름"이 된다.
        assertEquals(Duration.ofSeconds(300), CacheKeys.BIKE_STOCK_TTL);
        assertEquals(Duration.ofSeconds(180), CacheKeys.SUBWAY_ARRIVAL_TTL);
    }
}
