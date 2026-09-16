package com.ssafy.s15p21a104.domain.station.controller;

import com.ssafy.s15p21a104.domain.station.dto.response.StationSearchResultResponse;
import com.ssafy.s15p21a104.domain.station.service.StationSearchService;
import com.ssafy.s15p21a104.global.response.ApiResult;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequiredArgsConstructor
public class StationController implements StationApi {

    private final StationSearchService stationSearchService;

    @Override
    public ApiResult<List<StationSearchResultResponse>> search(String query) {
        return ApiResult.ok(stationSearchService.search(query));
    }
}
