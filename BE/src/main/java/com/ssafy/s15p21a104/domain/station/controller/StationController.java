package com.ssafy.s15p21a104.domain.station.controller;

import com.ssafy.s15p21a104.domain.station.dto.response.StationNearbyResponse;
import com.ssafy.s15p21a104.domain.station.dto.response.StationSearchResultResponse;
import com.ssafy.s15p21a104.domain.station.service.StationNearbyService;
import com.ssafy.s15p21a104.domain.station.service.StationSearchService;
import com.ssafy.s15p21a104.global.response.ApiResult;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequiredArgsConstructor
public class StationController implements StationApi {

    private final StationSearchService stationSearchService;
    private final StationNearbyService stationNearbyService;

    @Override
    public ApiResult<List<StationSearchResultResponse>> search(String query) {
        return ApiResult.ok(stationSearchService.search(query));
    }

    @Override
    public ApiResult<List<StationNearbyResponse>> nearby(
            Double lat, Double lng, Integer radiusMeters, Integer limit) {
        return ApiResult.ok(stationNearbyService.nearby(lat, lng, radiusMeters, limit));
    }
}
