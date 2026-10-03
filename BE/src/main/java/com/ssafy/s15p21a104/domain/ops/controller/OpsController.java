package com.ssafy.s15p21a104.domain.ops.controller;

import com.ssafy.s15p21a104.domain.ops.dto.response.BikeStockOverviewResponse;
import com.ssafy.s15p21a104.domain.ops.dto.response.CongestionHeatmapResponse;
import com.ssafy.s15p21a104.domain.ops.service.OpsBikeStockService;
import com.ssafy.s15p21a104.domain.ops.service.OpsCongestionHeatmapService;
import com.ssafy.s15p21a104.global.response.ApiResult;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
public class OpsController implements OpsApi {

    private final OpsBikeStockService opsBikeStockService;
    private final OpsCongestionHeatmapService opsCongestionHeatmapService;

    @Override
    public ApiResult<BikeStockOverviewResponse> bikeStockOverview(Double swLat, Double swLng, Double neLat,
                                                                  Double neLng, String arrivalTime, Integer limit) {
        return ApiResult.ok(opsBikeStockService.overview(swLat, swLng, neLat, neLng, arrivalTime, limit));
    }

    @Override
    public ApiResult<CongestionHeatmapResponse> congestionHeatmap(String date) {
        return ApiResult.ok(opsCongestionHeatmapService.heatmap(date));
    }
}
