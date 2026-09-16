package com.ssafy.s15p21a104.domain.route.bike.geometry;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import java.util.List;

/**
 * 카카오맵 자전거 경로 조회({@code GET /v2/routing/bicycle}) 응답(S15P21A104-222).
 *
 * <p>실제 호출(2026-09-15)로 확인한 스키마다 — 도보 API(S15P21A104-186)와 완전히 같은 구조다.
 * {@code status}가 {@code "OK"}면 {@code route.legs[].steps[].path.points}에
 * {@code [lng, lat]} 쌍 배열이 담긴다.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
record KakaoBikeDirectionsResponse(String status, KakaoRoute route) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    record KakaoRoute(List<KakaoLeg> legs) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    record KakaoLeg(List<KakaoStep> steps) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    record KakaoStep(KakaoPath path) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    record KakaoPath(List<List<Double>> points) {
    }
}
