package com.ssafy.s15p21a104.domain.bike.controller;

import com.ssafy.s15p21a104.domain.bike.dto.response.BikeStationResponse;
import com.ssafy.s15p21a104.domain.bike.dto.response.BikeStockResponse;
import com.ssafy.s15p21a104.domain.bike.service.BikeStationSearchService;
import com.ssafy.s15p21a104.global.response.ApiResult;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequiredArgsConstructor
public class BikeStationController implements BikeStationApi {

    private final BikeStationSearchService bikeStationSearchService;

    @Override
    public ApiResult<List<BikeStationResponse>> nearby(Double lat, Double lng, Integer radiusMeters, Integer limit) {
        return ApiResult.ok(bikeStationSearchService.nearby(lat, lng, radiusMeters, limit));
    }

    @Override
    public ApiResult<BikeStockResponse> stock(String rentalId) {
        return ApiResult.ok(bikeStationSearchService.stock(rentalId));
    }
}
