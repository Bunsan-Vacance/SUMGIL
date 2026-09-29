package com.ssafy.s15p21a104.domain.reroute.controller;

import com.ssafy.s15p21a104.domain.reroute.dto.request.RerouteRequest;
import com.ssafy.s15p21a104.domain.reroute.dto.response.RerouteResponse;
import com.ssafy.s15p21a104.global.response.ApiResult;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.util.List;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;

@Tag(name = "잔여 경로 재탐색")
@RequestMapping("/api/routes/replan")
public interface RerouteApi {

    @Operation(summary = "잔여 경로 재탐색 (S15P21A104-193)",
            description = "현 경계부터 목적지까지 잔여 후보를 반환한다. 빈 배열은 오류가 아니며 기존 안내 경로를 유지한다. "
                    + "route.totalMinutes는 잔여 legs 합과 0.01분 이내로 일치한다.")
    @PostMapping
    ApiResult<List<RerouteResponse>> replan(@RequestBody RerouteRequest request);
}
