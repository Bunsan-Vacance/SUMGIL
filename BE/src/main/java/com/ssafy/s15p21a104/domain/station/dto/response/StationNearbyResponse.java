package com.ssafy.s15p21a104.domain.station.dto.response;

import java.util.List;

/**
 * 근처 역 조회 결과 한 건. 물리 역 하나가 한 행이며 소속 노선은 {@code lines}에 모은다
 * (역 검색과 달리 노선별로 행을 나누지 않는다). {@code stationId}는 불투명 문자열이다.
 */
public record StationNearbyResponse(
        String stationId,
        String stationName,
        Double lat,
        Double lng,
        double distanceMeters,
        List<StationLineResponse> lines
) {
}
