package com.ssafy.s15p21a104.global.exception;

import lombok.Getter;

@Getter
public class DomainException extends RuntimeException {

    private final ErrorType errorType;

    public DomainException(ErrorType errorType) {
        super(errorType.getMessage());
        this.errorType = errorType;
    }

    @Override
    public synchronized Throwable fillInStackTrace() {
        return this;
    }
}
