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
        Double minutes,
        /** KTDB 실선로 좌표(미승인 필드). 매칭 안 되면 null — {@link #geometryStatus} 참고. */
        MultiLineStringResponse geometry,
        /** "available" | "unavailable". */
        String geometryStatus
) {
}
