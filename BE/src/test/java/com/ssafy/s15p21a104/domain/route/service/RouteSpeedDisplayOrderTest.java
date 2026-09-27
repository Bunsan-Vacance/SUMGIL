package com.ssafy.s15p21a104.domain.route.service;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.finder.RouteCandidateFinder;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 속도 그룹 표시 순서(S15P21A104-268) — 도보 표시 시간 정정(폴리라인) 뒤 총시간이 바뀌어도
 * SHORTEST가 속도 그룹에서 가장 빠른 후보에 붙어야 한다. 혼잡 그룹(LOW_CONGESTION 이후)은 혼잡순 유지.
 */
class RouteSpeedDisplayOrderTest {

    private static RouteSearchResponse route(RouteType type, double minutes) {
        return new RouteSearchResponse(type, minutes, List.of(), RouteSource.ALGORITHM, null, 0, null);
    }

    private static List<String> view(List<RouteSearchResponse> routes) {
        return routes.stream().map(r -> r.routeType() + ":" + r.totalMinutes()).toList();
    }

    @Test
    @DisplayName("268-1: 속도 그룹만 표시 총시간순으로 재정렬하고 1위에 SHORTEST — prod 멀티캠퍼스→산성 형태")
    void 속도그룹_재정렬() {
        List<RouteSearchResponse> reordered = RouteCandidateFinder.reorderSpeedByTotalMinutes(List.of(
                route(RouteType.SHORTEST, 36.9),
                route(RouteType.ALTERNATIVE, 35.9),
                route(RouteType.ALTERNATIVE, 43.3),
                route(RouteType.LOW_CONGESTION, 51.9),
                route(RouteType.ALTERNATIVE, 42.5),
                route(RouteType.ALTERNATIVE, 38.8)));

        assertEquals(List.of(
                "SHORTEST:35.9", "ALTERNATIVE:36.9", "ALTERNATIVE:43.3",
                "LOW_CONGESTION:51.9", "ALTERNATIVE:42.5", "ALTERNATIVE:38.8"), view(reordered));
    }

    @Test
    @DisplayName("268-2: 혼잡 후보가 없으면(LOW_CONGESTION 없음) 전체가 속도 그룹 — 총시간순, 동률은 기존 순서")
    void 혼잡없음_전체() {
        List<RouteSearchResponse> reordered = RouteCandidateFinder.reorderSpeedByTotalMinutes(List.of(
                route(RouteType.SHORTEST, 12.0),
                route(RouteType.ALTERNATIVE, 11.0),
                route(RouteType.ALTERNATIVE, 12.0)));

        assertEquals(List.of("SHORTEST:11.0", "ALTERNATIVE:12.0", "ALTERNATIVE:12.0"), view(reordered));
    }
}
