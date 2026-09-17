package com.ssafy.s15p21a104.domain.reroute;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;

/**
 * 잔여 경로 대안 1건(S15P21A104-193, FE 문서 §5.2 계약).
 *
 * @param reason 대안 이유 (FE 표시용, 필수)
 * @param source ALGORITHM 고정 (MOCK은 FE가 자체 처리)
 * @param route 잔여 legs만 담은 경로 (현 경계 시작 → 목적지 끝)
 */
public record RerouteResult(
        String reason,
        String source,
        RouteSearchResponse route
) {
}
