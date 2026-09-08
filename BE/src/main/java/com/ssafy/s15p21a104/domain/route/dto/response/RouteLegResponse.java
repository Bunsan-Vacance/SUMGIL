package com.ssafy.s15p21a104.domain.route.dto.response;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;

public record RouteLegResponse(
        TravelMode mode,
        String fromNodeId,
        String fromNodeName,
        Double fromLat,
        Double fromLng,
        String toNodeId,
        String toNodeName,
        Double toLat,
        Double toLng,
        String routeId,
        Double minutes
) {
}
