package com.ssafy.s15p21a104.collect.publish;

/** 이벤트 전송 실패. 회차 안에서 일부만 실패했을 수 있어 성공·실패 건수를 함께 담는다. */
public class PublishException extends RuntimeException {

    private final int sent;
    private final int failed;

    public PublishException(String message, int sent, int failed, Throwable cause) {
        super(message, cause);
        this.sent = sent;
        this.failed = failed;
    }

    public int sent() {
        return sent;
    }

    public int failed() {
        return failed;
    }
}
