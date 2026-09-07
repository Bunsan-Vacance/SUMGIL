package com.ssafy.s15p21a104.global.exception;

import org.springframework.http.HttpStatus;

/**
 * 에러 코드 규격. 공통은 {@code ErrorType}, 도메인별은 각 도메인 패키지에서 구현한다.
 */
public interface ErrorCode {

    HttpStatus getStatus();

    String getCode();

    String getMessage();
}
