package com.ssafy.s15p21a104.domain.route.dto.request;

/** 경로 정렬/계산 우선순위. 값·의미는 추천 로직이 구체화되면 조정한다 (BE/docs/api/api-spec.md 참고). */
public enum RoutePriority {
    TIME,
    COMFORT
}
