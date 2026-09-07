package com.ssafy.s15p21a104.api.test;

import com.ssafy.s15p21a104.api.test.dto.EchoRequest;
import com.ssafy.s15p21a104.api.test.dto.EchoResponse;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import com.ssafy.s15p21a104.global.response.ApiResult;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
public class TestController implements TestApi {

    @Override
    public ApiResult<EchoResponse> ok(EchoRequest request) {
        return ApiResult.ok(EchoResponse.builder()
                .greeting("hello, " + request.getName())
                .repeated(request.getCount())
                .build());
    }

    @Override
    public ApiResult<String> fail() {
        throw new DomainException(ErrorType.BAD_REQUEST);
    }
}
