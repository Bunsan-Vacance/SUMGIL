package com.ssafy.s15p21a104.domain.route.controller;

import com.ssafy.s15p21a104.domain.route.dto.request.CoordinateRouteSearchRequest;
import com.ssafy.s15p21a104.domain.route.dto.request.RoutePriority;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.global.response.ApiResult;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

import java.time.LocalDateTime;
import java.util.List;

@Tag(name = "경로")
@RequestMapping("/api/routes")
public interface RouteApi {

    @Operation(summary = "경로 검색", description = "출발역·도착역 기준 경로 후보 목록을 우선순위 순으로 반환한다. "
            + "departureTime 생략 시 현재 시각 기준(dow_type·time_slot 조회용, S15P21A104-63 확장).")
    @GetMapping("/search")
    ApiResult<List<RouteSearchResponse>> search(
            @RequestParam String originStationId,
            @RequestParam String destStationId,
            @RequestParam(required = false) List<TravelMode> modes,
            @RequestParam(required = false) RoutePriority priority,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime departureTime
    );

    @Operation(summary = "좌표 기반 경로 검색 (계약·입력 검증, S15P21A104-185)",
            description = "역 ID 대신 출발·도착 WGS84 좌표를 받는다. 일반 장소를 역 DB에 등록하지 않고 요청을 수용한다. "
                    + "이 티켓 범위는 계약·입력 검증까지이며, 좌표-교통망 연결(접근 후보 탐색·보행 계산)은 후속 작업의 "
                    + "책임이다 — 유효한 요청이어도 아직 501 ACCESS_CANDIDATE_NOT_READY를 반환한다.")
    @PostMapping("/search/coordinate")
    ApiResult<List<RouteSearchResponse>> searchByCoordinate(@RequestBody CoordinateRouteSearchRequest request);
}
