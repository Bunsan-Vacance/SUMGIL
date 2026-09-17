package com.ssafy.s15p21a104.domain.reroute.dto.response;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import java.util.List;

/**
 * 잔여 경로 재탐색 응답(S15P21A104-193, FE 문서 §5.2 계약).
 *
 * @param reason 대안 이유 (필수)
 * @param source ALGORITHM 고정
 * @param route 잔여 legs 경로
 */
public record RerouteResponse(
        String reason,
        String source,
        RouteSearchResponse route
) {
    public static RerouteResponse of(String reason, String source, RouteSearchResponse route) {
        return new RerouteResponse(reason, source, route);
    }

    public static List<RerouteResponse> listOf(
            List<com.ssafy.s15p21a104.domain.reroute.RerouteResult> results) {
        return results.stream()
                .map(r -> new RerouteResponse(r.reason(), r.source(), r.route()))
                .toList();
    }
}
