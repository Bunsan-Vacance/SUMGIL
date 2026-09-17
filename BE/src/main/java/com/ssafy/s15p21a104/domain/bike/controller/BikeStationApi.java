package com.ssafy.s15p21a104.domain.bike.controller;

import com.ssafy.s15p21a104.domain.bike.dto.response.BikeStationResponse;
import com.ssafy.s15p21a104.domain.bike.dto.response.BikeStockResponse;
import com.ssafy.s15p21a104.global.response.ApiResult;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

import java.util.List;

@Tag(name = "따릉이 대여소")
@RequestMapping("/api/bike-stations")
public interface BikeStationApi {

    @Operation(summary = "근처 대여소 조회", description = "좌표 기준 반경 안의 따릉이 대여소를 거리순으로 반환한다. "
            + "availableBikes·stockUpdatedAt은 실시간 재고 캐시가 있을 때만 채워지고, 없으면 둘 다 null이다(에러 아님). "
            + "신선/오래됨 구분이 필요하면 단건 조회를 쓴다.")
    @GetMapping("/nearby")
    ApiResult<List<BikeStationResponse>> nearby(
            @RequestParam Double lat,
            @RequestParam Double lng,
            @RequestParam(required = false) Integer radiusMeters,
            @RequestParam(required = false) Integer limit
    );

    @Operation(summary = "대여소 단건 실시간 재고 조회", description = "서울시 공공자전거 API를 다시 호출하지 않고 "
            + "수집기가 Redis에 적재해 둔 최신 재고를 읽는다(수집 주기 120초). status로 신뢰도를 구분한다 — "
            + "AVAILABLE(신선도 창 180초 이내), STALE(캐시는 있지만 180초를 넘김, 마지막 값·시각을 그대로 반환), "
            + "UNAVAILABLE(캐시 없음·TTL 300초 만료, 값은 전부 null). 등록되지 않은 rentalId는 404다.")
    @GetMapping("/{rentalId}/stock")
    ApiResult<BikeStockResponse> stock(@PathVariable String rentalId);
}
