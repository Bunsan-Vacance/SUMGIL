package com.ssafy.s15p21a104.global.response;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.ssafy.s15p21a104.global.exception.ErrorCode;
import java.time.Instant;

/**
 * 응답 래퍼. 컨트롤러는 {@code ApiResult.ok(data)}만 반환하고,
 * 오류는 {@code DomainException}을 던지면 핸들러가 변환한다.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ApiResult<T>(
        boolean success,
        Instant timestamp,
        String traceId,
        T data,
        ApiError error
) {

    public record ApiError(int status, String code, String message) {
    }

    public static <T> ApiResult<T> ok(T data) {
        return new ApiResult<>(true, Instant.now(), TraceId.get(), data, null);
    }

    public static <T> ApiResult<T> fail(ErrorCode errorCode) {
        return fail(errorCode, errorCode.getMessage());
    }

    public static <T> ApiResult<T> fail(ErrorCode errorCode, String message) {
        return new ApiResult<>(false, Instant.now(), TraceId.get(), null,
                new ApiError(errorCode.getStatus().value(), errorCode.getCode(), message));
    }
}
