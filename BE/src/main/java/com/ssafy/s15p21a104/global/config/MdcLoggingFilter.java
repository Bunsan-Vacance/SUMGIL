package com.ssafy.s15p21a104.global.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * X-Trace-Id 수용/발급 · 응답 헤더 에코 · MDC 적재.
 * ApiResult.traceId는 MDC에서 꺼낸다.
 *
 * <p>요청 정보는 method·uri·status만 적재한다. params·payload·headers·clientIp는
 * 제외한다. 위치 좌표가 쿼리·본문에 들어있어 로그에 원문을 남기지 않는 원칙과
 * 충돌하기 때문이다.
 */
@Component
@Slf4j
public class MdcLoggingFilter extends OncePerRequestFilter {

    private static final String TRACE_ID = "traceId";
    private static final String TRACE_HEADER = "X-Trace-Id";

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        String traceId = request.getHeader(TRACE_HEADER);
        if (traceId == null || traceId.isBlank()) {
            traceId = UUID.randomUUID().toString();
        }
        MDC.put(TRACE_ID, traceId);
        MDC.put("method", request.getMethod());
        MDC.put("uri", request.getRequestURI());
        response.setHeader(TRACE_HEADER, traceId);
        try {
            filterChain.doFilter(request, response);
        } finally {
            MDC.put("status", String.valueOf(response.getStatus()));
            log.info("{} {} -> {}", request.getMethod(), request.getRequestURI(),
                    response.getStatus());
            MDC.clear();
        }
    }
}
