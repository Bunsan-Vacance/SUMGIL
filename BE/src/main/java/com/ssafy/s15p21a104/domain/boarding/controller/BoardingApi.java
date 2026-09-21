package com.ssafy.s15p21a104.domain.boarding.controller;

import com.ssafy.s15p21a104.domain.boarding.dto.request.BoardingRequest;
import com.ssafy.s15p21a104.domain.boarding.dto.response.BoardingResponse;
import com.ssafy.s15p21a104.global.response.ApiResult;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;

@Tag(name = "탑승 확인")
@RequestMapping("/api/boardings")
public interface BoardingApi {

    @Operation(summary = "탑승 확인 이벤트 기록 (S15P21A104-313)",
            description = "사용자가 특정 구간에 탑승했는지(또는 어느 열차/버스에 탑승했는지) 체크한 결과를 기록한다. "
                    + "로그인이 없어 사용자를 식별하지 않으며, AI·다른 BE 도메인은 boarding_event 테이블을 직접 읽어 쓴다. "
                    + "mode/fromNodeId/toNodeId/status/reportedAt이 없으면 BAD_REQUEST.")
    @PostMapping
    ApiResult<BoardingResponse> record(@RequestBody BoardingRequest request);
}
