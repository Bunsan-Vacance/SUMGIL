package com.ssafy.s15p21a104.domain.congestion.controller;

import com.ssafy.s15p21a104.domain.congestion.dto.response.CongestionBatchResponse;
import com.ssafy.s15p21a104.domain.congestion.dto.response.CongestionResponse;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionTarget;
import com.ssafy.s15p21a104.global.response.ApiResult;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.time.LocalDateTime;
import java.util.List;
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

    @Operation(summary = "혼잡도 일괄 조회", description = "여러 대상(역·노선 등)의 여러 시각 혼잡도를 한 번에 조회한다. "
            + "단건 조회와 같은 congestion 표·같은 슬롯 규칙(dow_type·time_slot, DepartureSlot)을 쓰므로 값이 같다. "
            + "targetIds는 쉼표로 구분하며 공백·빈 값·중복은 정리하고 1~50개를 받는다. "
            + "departureTimes는 쉼표로 구분한 ISO LocalDateTime이며 생략하면 현재 시각 1개이고 1~12개를 받는다. "
            + "대상×시각 조합은 최대 200개이며 넘으면 400 CONGESTION_BATCH_TOO_LARGE를 돌려준다. "
            + "모든 조합을 요청 순서대로 돌려주고, 데이터 없는 조합은 level·source·updatedAt이 null이다"
            + "(0이나 추정값으로 바꾸지 않음). 존재하지 않는 targetId도 404가 아니라 null 행이다. "
            + "targetIds가 비면 400 BAD_REQUEST, 잘못된 targetType이나 시각 형식도 400 BAD_REQUEST다.")
    @GetMapping("/batch")
    ApiResult<CongestionBatchResponse> getCongestionBatch(
            @RequestParam CongestionTarget targetType,
            @RequestParam List<String> targetIds,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) List<LocalDateTime> departureTimes
    );
}
