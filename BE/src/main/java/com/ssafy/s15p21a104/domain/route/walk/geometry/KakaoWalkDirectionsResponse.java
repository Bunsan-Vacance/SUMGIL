package com.ssafy.s15p21a104.domain.route.walk.geometry;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

/**
 * 카카오맵 도보 경로 조회 응답(잠정 스키마, S15P21A104-186). 실제 사용 전 콘솔 원문 문서로
 * 필드명 대조 확인이 필요하다 — 카카오모빌리티 길찾기 API군과 같은 구조(routes/sections/roads)로 추정한다.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
record KakaoWalkDirectionsResponse(List<KakaoRoute> routes) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    record KakaoRoute(
            @JsonProperty("result_code") Integer resultCode,
            List<KakaoSection> sections
    ) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    record KakaoSection(List<KakaoRoad> roads) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    record KakaoRoad(List<Double> vertexes) {
    }
}
