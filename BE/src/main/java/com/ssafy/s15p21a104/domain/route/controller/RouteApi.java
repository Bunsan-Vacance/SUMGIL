package com.ssafy.s15p21a104.domain.route.controller;

import com.ssafy.s15p21a104.domain.route.dto.request.RoutePriority;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.global.response.ApiResult;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

import java.util.List;

@Tag(name = "경로")
@RequestMapping("/api/routes")
public interface RouteApi {

    @Operation(summary = "경로 검색", description = "출발역·도착역 기준 경로 후보 목록을 우선순위 순으로 반환한다.")
    @GetMapping("/search")
    ApiResult<List<RouteSearchResponse>> search(
            @RequestParam String originStationId,
            @RequestParam String destStationId,
            @RequestParam(required = false) List<TravelMode> modes,
            @RequestParam(required = false) RoutePriority priority
    );
}
