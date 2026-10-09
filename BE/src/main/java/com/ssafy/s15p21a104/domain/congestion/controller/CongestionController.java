package com.ssafy.s15p21a104.domain.congestion.controller;

import com.ssafy.s15p21a104.domain.congestion.dto.response.CongestionBatchResponse;
import com.ssafy.s15p21a104.domain.congestion.dto.response.CongestionResponse;
import com.ssafy.s15p21a104.domain.congestion.entity.CongestionTarget;
import com.ssafy.s15p21a104.domain.congestion.service.CongestionQueryService;
import com.ssafy.s15p21a104.global.response.ApiResult;
import java.time.LocalDateTime;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
public class CongestionController implements CongestionApi {

    private final CongestionQueryService congestionQueryService;

    @Override
    public ApiResult<CongestionResponse> getCongestion(
            CongestionTarget targetType, String targetId, LocalDateTime departureTime) {
        return ApiResult.ok(congestionQueryService.find(targetType, targetId, departureTime));
    }

    @Override
    public ApiResult<CongestionBatchResponse> getCongestionBatch(
            CongestionTarget targetType, List<String> targetIds, List<LocalDateTime> departureTimes) {
        return ApiResult.ok(congestionQueryService.findBatch(targetType, targetIds, departureTimes));
    }
}
