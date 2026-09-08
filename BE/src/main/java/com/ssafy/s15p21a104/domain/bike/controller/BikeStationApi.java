package com.ssafy.s15p21a104.domain.bike.controller;

import com.ssafy.s15p21a104.domain.bike.dto.response.BikeStationResponse;
import com.ssafy.s15p21a104.global.response.ApiResult;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

import java.util.List;

@Tag(name = "따릉이 대여소")
@RequestMapping("/api/bike-stations")
public interface BikeStationApi {

    @Operation(summary = "근처 대여소 조회", description = "좌표 기준 반경 안의 따릉이 대여소를 거리순으로 반환한다. 실시간 재고는 포함하지 않는다.")
    @GetMapping("/nearby")
    ApiResult<List<BikeStationResponse>> nearby(
            @RequestParam Double lat,
            @RequestParam Double lng,
            @RequestParam(required = false) Integer radiusMeters,
            @RequestParam(required = false) Integer limit
    );
}
