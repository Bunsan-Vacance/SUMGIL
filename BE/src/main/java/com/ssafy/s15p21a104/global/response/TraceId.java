package com.ssafy.s15p21a104.global.response;

import org.slf4j.MDC;

public final class TraceId {

    private TraceId() {
    }

    public static String get() {
        String id = MDC.get("traceId");
        return (id != null) ? id : "N/A";
    }
}
