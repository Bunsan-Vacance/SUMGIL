package com.ssafy.s15p21a104.global.cache;

import java.time.Duration;

/**
 * Redis 캐시 키 네이밍 규칙과 TTL 정책.
 * 실시간 값을 채우는 쪽은 Redis 반영 컨슈머(S15P21A104-171, {@code consume} 패키지)다.
 * 정책 배경은 BE/docs/cache/strategy.md, 실시간 값 모양은 BE/docs/infra/consumer.md 참고.
 */
public final class CacheKeys {

    /** 지하철 실시간 도착 상태. 역별 키가 없을 때 "정보 없음 / 운영창 밖 / 수집 지연" 을 가르는 단 하나의 키 (171). */
    public static final String SUBWAY_ARRIVAL_STATUS = "subway:arrival:status";

    /** 역전구간 판정 결과 (사전계산). dow_type·time_slot 단위로 값이 바뀌므로 슬롯 하나만큼만 유효하다. */
    public static final Duration REVERSAL_TTL = Duration.ofMinutes(30);

    /**
     * 실시간 재고. 수집이 멈추면 만료되어 "재고 모름" 상태가 되어야 한다.
     *
     * <p>수집 주기가 120초다(170). 한 회차를 놓치고 서킷 브레이커 60초까지 겹쳐도 버티도록 300초로 둔다 —
     * 주기보다 짧으면 수집이 멀쩡해도 회차 사이마다 키가 사라져 자전거 추천이 그만큼 막힌다.
     * 두 회차를 연속으로 놓치면 만료되는 것이 의도다. (61 의 90초에서 171 에서 조정)
     */
    public static final Duration BIKE_STOCK_TTL = Duration.ofSeconds(300);

    /** 실시간 도착. 수집 주기 60초 기준, 위와 같은 규칙으로 한 회차 + 서킷 브레이커를 버티는 180초 (171). */
    public static final Duration SUBWAY_ARRIVAL_TTL = Duration.ofSeconds(180);

    private CacheKeys() {
    }

    public static String reversal(String originStationId, String destStationId, int dowType, int timeSlot) {
        return "reversal:%s:%s:%d:%d".formatted(originStationId, destStationId, dowType, timeSlot);
    }

    public static String bikeStock(String rentalId) {
        return "bike:stock:%s".formatted(rentalId);
    }

    /** @param stationId 우리 역번호. API 의 statnId 가 아니다 — 변환은 {@code consume.StatnIdMap} 이 한다 */
    public static String subwayArrival(String stationId) {
        return "subway:arrival:%s".formatted(stationId);
    }
}
