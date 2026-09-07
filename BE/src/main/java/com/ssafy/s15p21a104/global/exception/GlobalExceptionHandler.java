package com.ssafy.s15p21a104.global.exception;

import com.ssafy.s15p21a104.global.response.ApiResult;
import jakarta.servlet.http.HttpServletRequest;
import java.util.stream.Collectors;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.FieldError;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

@RestControllerAdvice
@Slf4j
public class GlobalExceptionHandler {

    @ExceptionHandler(DomainException.class)
    public ResponseEntity<ApiResult<Void>> handleDomainException(
            DomainException exception, HttpServletRequest request) {
        ErrorCode errorCode = exception.getErrorCode();
        log.warn("[Domain] {} {} -> {} {}", request.getMethod(), request.getRequestURI(),
                errorCode.getCode(), exception.getMessage());
        return ResponseEntity
                .status(errorCode.getStatus())
                .body(ApiResult.fail(errorCode));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiResult<Void>> handleValidationException(
            MethodArgumentNotValidException exception, HttpServletRequest request) {
        String message = exception.getBindingResult()
                .getFieldErrors()
                .stream()
                .map(this::formatFieldError)
                .collect(Collectors.joining(", "));
        log.warn("[Validation] {} {} -> {}", request.getMethod(), request.getRequestURI(), message);

        return ResponseEntity
                .status(ErrorType.BAD_REQUEST.getStatus())
                .body(ApiResult.fail(ErrorType.BAD_REQUEST,
                        message.isBlank() ? ErrorType.BAD_REQUEST.getMessage() : message));
    }

    @ExceptionHandler({
            MissingServletRequestParameterException.class,
            MethodArgumentTypeMismatchException.class,
            HttpMessageNotReadableException.class
    })
    public ResponseEntity<ApiResult<Void>> handleBadRequest(
            Exception exception, HttpServletRequest request) {
        log.warn("[BadRequest] {} {} -> {}", request.getMethod(), request.getRequestURI(),
                exception.getMessage());
        return ResponseEntity
                .status(ErrorType.BAD_REQUEST.getStatus())
                .body(ApiResult.fail(ErrorType.BAD_REQUEST));
    }

    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<ApiResult<Void>> handleNoResource(
            NoResourceFoundException exception, HttpServletRequest request) {
        log.warn("[NotFound] {} {}", request.getMethod(), request.getRequestURI());
        return ResponseEntity
                .status(ErrorType.NOT_FOUND.getStatus())
                .body(ApiResult.fail(ErrorType.NOT_FOUND));
    }

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<ApiResult<Void>> handleMethodNotSupported(
            HttpRequestMethodNotSupportedException exception, HttpServletRequest request) {
        log.warn("[MethodNotAllowed] {} {}", request.getMethod(), request.getRequestURI());
        return ResponseEntity
                .status(ErrorType.METHOD_NOT_ALLOWED.getStatus())
                .body(ApiResult.fail(ErrorType.METHOD_NOT_ALLOWED));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiResult<Void>> handleException(
            Exception exception, HttpServletRequest request) {
        log.error("[Unhandled] {} {}", request.getMethod(), request.getRequestURI(), exception);
        return ResponseEntity
                .status(ErrorType.INTERNAL_SERVER_ERROR.getStatus())
                .body(ApiResult.fail(ErrorType.INTERNAL_SERVER_ERROR));
    }

    private String formatFieldError(FieldError fieldError) {
        return fieldError.getField() + ": " + fieldError.getDefaultMessage();
    }
}
