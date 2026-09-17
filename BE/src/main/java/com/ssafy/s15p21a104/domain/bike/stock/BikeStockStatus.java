package com.ssafy.s15p21a104.domain.bike.stock;

/** 대여소 단건 실시간 재고 조회 응답의 신뢰도 구분 (BIKE-001 156). */
public enum BikeStockStatus {
    /** 신선도 창(BIKE_STOCK_FRESH_WINDOW) 안의 최신 값. 자전거 수가 0이어도 AVAILABLE이다 — "값이 유효함"의 의미다. */
    AVAILABLE,
    /** 캐시는 있지만 신선도 창을 넘겼다. 마지막 값·시각을 그대로 내려주되 최신으로 단정하지 않는다. */
    STALE,
    /** 캐시가 없다(TTL 만료 포함) — 재고를 알 수 없다. 에러가 아니다. */
    UNAVAILABLE
}
