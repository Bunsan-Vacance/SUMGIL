package com.ssafy.s15p21a104.global.cache;

import java.time.Duration;

/**
 * Redis 캐시 키 네이밍 규칙과 TTL 정책.
 * 실제 캐시 채움(사전계산 결과 적재, 스트림 갱신)은 데이터 파이프라인 연동 후 별도 작업에서 구현한다.
 * 정책 배경은 BE/docs/cache/strategy.md 참고.
 */
public final class CacheKeys {

    /** 역전구간 판정 결과 (사전계산). dow_type·time_slot 단위로 값이 바뀌므로 슬롯 하나만큼만 유효하다. */
    public static final Duration REVERSAL_TTL = Duration.ofMinutes(30);

    /** 실시간 재고. 스트림이 갱신을 멈추면 곧바로 만료되어 "재고 모름" 상태가 되어야 한다. */
    public static final Duration BIKE_STOCK_TTL = Duration.ofSeconds(90);

    private CacheKeys() {
    }

    public static String reversal(String originStationId, String destStationId, int dowType, int timeSlot) {
        return "reversal:%s:%s:%d:%d".formatted(originStationId, destStationId, dowType, timeSlot);
    }

    public static String bikeStock(String rentalId) {
        return "bike:stock:%s".formatted(rentalId);
    }
}
