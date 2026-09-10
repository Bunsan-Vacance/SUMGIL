package com.ssafy.s15p21a104.domain.route.controller;

import com.ssafy.s15p21a104.domain.route.dto.request.RoutePriority;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.service.RouteSearchService;
import com.ssafy.s15p21a104.global.response.ApiResult;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.List;

@RestController
@RequiredArgsConstructor
public class RouteController implements RouteApi {

    private final RouteSearchService routeSearchService;

    @Override
    public ApiResult<List<RouteSearchResponse>> search(
            String originStationId,
            String destStationId,
            List<TravelMode> modes,
            RoutePriority priority,
            LocalDateTime departureTime
    ) {
        return ApiResult.ok(
                routeSearchService.search(originStationId, destStationId, modes, priority, departureTime));
    }
}
