package com.ssafy.s15p21a104.domain.bike.dto.response;

import java.time.OffsetDateTime;

/**
 * @param availableBikes 실시간 재고. 캐시 없음·만료면 null이다(에러 아님, BIKE-001 156). 신선/오래됨 구분이 필요하면
 *                        단건 조회({@code GET /api/bike-stations/{rentalId}/stock})를 쓴다 — 목록은 값 유무만 준다.
 * @param stockUpdatedAt availableBikes가 null이면 같이 null이다.
 */
public record BikeStationResponse(
        String rentalId,
        String name,
        Double lat,
        Double lng,
        Integer dockCount,
        Double distanceMeters,
        Integer availableBikes,
        OffsetDateTime stockUpdatedAt
) {
}
