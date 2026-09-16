package com.ssafy.s15p21a104.domain.route.dto.response;

/** 초기 제공 유형만 정의한다. */
public enum RouteType {
    SHORTEST,
    SHORTEST_WITH_BIKE,
    /** 허용 수단 조합별 대체 후보(S15P21A104-185). 전체 후보 중 SHORTEST가 아닌 나머지. */
    ALTERNATIVE,
    /**
     * priority=COMFORT 요청에서 혼잡도가 가장 낮게 산출된 후보(S15P21A104-157). 실제 혼잡도
     * 데이터로 점수를 계산할 수 있었을 때만 붙는다 — 데이터가 없으면 이 값을 만들어내지 않는다.
     */
    LOW_CONGESTION
}
