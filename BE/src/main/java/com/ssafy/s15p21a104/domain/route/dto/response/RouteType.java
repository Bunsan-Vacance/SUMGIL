package com.ssafy.s15p21a104.domain.route.dto.response;

/** 초기 제공 유형만 정의한다. 혼잡회피 등은 관련 데이터(S15P21A104-73) 준비 후 추가한다. */
public enum RouteType {
    SHORTEST,
    SHORTEST_WITH_BIKE,
    /** 허용 수단 조합별 대체 후보(S15P21A104-185). 전체 후보 중 SHORTEST가 아닌 나머지. */
    ALTERNATIVE
}
