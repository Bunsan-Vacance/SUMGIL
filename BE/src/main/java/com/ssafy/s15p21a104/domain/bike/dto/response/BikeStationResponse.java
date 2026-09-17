package com.ssafy.s15p21a104.domain.bike.dto.response;

public record BikeStationResponse(
        String rentalId,
        String name,
        Double lat,
        Double lng,
        Integer dockCount,
        Double distanceMeters
) {
}
