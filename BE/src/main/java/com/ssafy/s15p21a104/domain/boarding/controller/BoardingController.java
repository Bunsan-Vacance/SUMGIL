package com.ssafy.s15p21a104.domain.boarding.controller;

import com.ssafy.s15p21a104.domain.boarding.dto.request.BoardingRequest;
import com.ssafy.s15p21a104.domain.boarding.dto.response.BoardingResponse;
import com.ssafy.s15p21a104.domain.boarding.service.BoardingService;
import com.ssafy.s15p21a104.global.response.ApiResult;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
public class BoardingController implements BoardingApi {

    private final BoardingService boardingService;

    @Override
    public ApiResult<BoardingResponse> record(BoardingRequest request) {
        return ApiResult.ok(boardingService.record(request));
    }
}
