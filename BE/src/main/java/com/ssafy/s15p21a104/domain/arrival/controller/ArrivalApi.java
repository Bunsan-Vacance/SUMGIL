package com.ssafy.s15p21a104.domain.arrival.controller;

import com.ssafy.s15p21a104.domain.arrival.dto.response.ArrivalResponse;
import com.ssafy.s15p21a104.global.response.ApiResult;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

@Tag(name = "실시간 도착")
@RequestMapping("/api/transit/arrivals")
public interface ArrivalApi {

    @Operation(summary = "실시간 열차 도착 조회 (S15P21A104-192)",
            description = "역의 실시간 도착 후보를 반환한다. stationId 필수, routeId 선택(해당 노선만). "
                    + "빈 배열은 확인할 도착 정보가 없다는 뜻이며 오류가 아니다. "
                    + "수집 지연·운영창 밖은 status로 구분한다.")
    @GetMapping
    ApiResult<ArrivalResponse> arrivals(
            @RequestParam String stationId,
            @RequestParam(required = false) String routeId
    );
}
