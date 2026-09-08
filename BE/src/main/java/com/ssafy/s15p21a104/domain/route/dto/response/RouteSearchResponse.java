package com.ssafy.s15p21a104.domain.route.dto.response;

import java.util.List;

public record RouteSearchResponse(
        RouteType routeType,
        Double totalMinutes,
        List<RouteLegResponse> legs,
        RouteSource source
) {
}
