package com.ssafy.s15p21a104.api.test;

import com.ssafy.s15p21a104.api.test.dto.EchoRequest;
import com.ssafy.s15p21a104.api.test.dto.EchoResponse;
import com.ssafy.s15p21a104.global.response.ApiResult;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;

@Tag(name = "Test", description = "래퍼 동작 확인용")
@RequestMapping("/api/v1/test")
public interface TestApi {

    @Operation(summary = "정상 응답 (요청·응답 DTO 확인)")
    @PostMapping("/ok")
    ApiResult<EchoResponse> ok(@Valid @RequestBody EchoRequest request);

    @Operation(summary = "비정상 응답 (BAD_REQUEST)")
    @GetMapping("/fail")
    ApiResult<String> fail();
}
