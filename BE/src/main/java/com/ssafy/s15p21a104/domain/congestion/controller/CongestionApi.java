package com.ssafy.s15p21a104.domain.congestion.controller;

import com.ssafy.s15p21a104.domain.congestion.dto.response.CongestionResponse;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionTarget;
import com.ssafy.s15p21a104.global.response.ApiResult;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.time.LocalDateTime;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

@Tag(name = "혼잡도")
@RequestMapping("/api/congestion")
public interface CongestionApi {

    @Operation(summary = "혼잡도 조회", description = "대상(역·노선 등)의 특정 시간대 혼잡도를 조회한다. "
            + "departureTime 생략 시 현재 시각 기준(dow_type·time_slot 산정, S15P21A104-63 DepartureSlot 재사용). "
            + "데이터 없는 조합이면 200 응답에 data 없이 돌아간다(값을 지어내지 않음).")
    @GetMapping
    ApiResult<CongestionResponse> getCongestion(
            @RequestParam CongestionTarget targetType,
            @RequestParam String targetId,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime departureTime
    );
}
