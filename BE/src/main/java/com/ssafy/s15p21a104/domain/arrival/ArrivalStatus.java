package com.ssafy.s15p21a104.domain.arrival;

/**
 * 실시간 도착 상태 구분(S15P21A104-192).
 * {@code consume.ArrivalStatus}의 수집기 상태와 역별 키 유무를 합쳐 읽는 쪽 기준으로 가른다.
 */
public enum ArrivalStatus {
    /** 실시간 도착 정보 있음. */
    LIVE,
    /** 역별 키 없음 + 수집 정상 — 그 역에 정보 없음 (열차 없음·미수집 역). */
    NO_INFO,
    /** 운영창 밖 — 장애가 아니다. */
    OUTSIDE_WINDOW,
    /** 수집 지연 중 — 오래된 값을 정상값으로 반환하지 않는다. */
    STALE
}
