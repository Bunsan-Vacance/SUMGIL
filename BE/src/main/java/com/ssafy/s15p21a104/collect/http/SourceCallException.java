package com.ssafy.s15p21a104.collect.http;

/**
 * 외부 소스 호출 실패. 어댑터 규칙(DataPart §2·NFR-EXT-002)대로 재시도 가능 여부를 종류로 가른다:
 * 타임아웃·IO·5xx 는 재시도, 4xx·API 오류 코드·파싱 실패는 재시도하지 않는다.
 *
 * <p>메시지에는 인증키를 가린 URL 만 들어간다 — 로그에 키가 새지 않게 하는 마지막 방어선이다.
 */
public class SourceCallException extends RuntimeException {

    public enum Kind { TIMEOUT, IO, HTTP_5XX, HTTP_4XX, API_ERROR, PARSE }

    private final Kind kind;
    private final Integer status;
    private final String code;

    public SourceCallException(Kind kind, String message, Integer status, String code, Throwable cause) {
        super(message, cause);
        this.kind = kind;
        this.status = status;
        this.code = code;
    }

    public static SourceCallException timeout(String redactedUrl, Throwable cause) {
        return new SourceCallException(Kind.TIMEOUT, "타임아웃: " + redactedUrl, null, null, cause);
    }

    public static SourceCallException io(String redactedUrl, Throwable cause) {
        return new SourceCallException(Kind.IO, "연결 실패: " + redactedUrl + " — " + cause.getMessage(), null, null, cause);
    }

    public static SourceCallException http(String redactedUrl, int status) {
        Kind kind = status >= 500 ? Kind.HTTP_5XX : Kind.HTTP_4XX;
        return new SourceCallException(kind, "HTTP " + status + ": " + redactedUrl, status, null, null);
    }

    public static SourceCallException apiError(String source, String code, String message) {
        return new SourceCallException(Kind.API_ERROR,
                source + " 응답 오류 code=" + code + " message=" + message, null, code, null);
    }

    public static SourceCallException parse(String source, Throwable cause) {
        return new SourceCallException(Kind.PARSE, source + " 응답을 JSON 으로 읽지 못했다: " + cause.getMessage(),
                null, null, cause);
    }

    public Kind kind() {
        return kind;
    }

    public Integer status() {
        return status;
    }

    public String code() {
        return code;
    }

    /** 타임아웃·IO·5xx 만 true. 4xx 는 우리 요청이 틀린 것이라 다시 보내도 같다. */
    public boolean retryable() {
        return kind == Kind.TIMEOUT || kind == Kind.IO || kind == Kind.HTTP_5XX;
    }
}
