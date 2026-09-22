package com.ssafy.s15p21a104.domain.route.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.FoundPath;
import com.ssafy.s15p21a104.domain.route.finder.RouteCandidateFinder;
import com.ssafy.s15p21a104.domain.route.finder.ScoredCandidate;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 응답 계약 채점용 원본 엣지 맵 테스트(2026-09-22) — 보장용으로 주입한 후보가 맵에서 빠져
 * 링크 혼잡 채점을 못 받던 결함(prod: 도보 후보 WEEKDAY_AVERAGE vs 따릉이 후보 RECENT_7D)을
 * 재발 방지한다.
 */
class ContractEdgeMapTest {

    private static ScoredCandidate candidate(String routeId, String from, String to) {
        Edge edge = new Edge(from, to, routeId, 600, 0, TravelMode.SUBWAY);
        FoundPath path = new FoundPath(List.of(from, to), List.of(edge), 600, 0);
        RouteLegResponse leg = new RouteLegResponse(TravelMode.SUBWAY, from, from, 37.5, 127.0,
                to, to, 37.51, 127.01, routeId, 10.0, null, "unavailable", null, null, null);
        RouteSearchResponse response = new RouteSearchResponse(RouteType.ALTERNATIVE, 10.0,
                List.of(leg), RouteSource.ALGORITHM, null, 0, null);
        return new ScoredCandidate(response, path);
    }

    @Test
    @DisplayName("주입 후보의 원본 엣지도 맵에 들어간다 — 링크 채점 누락 방지")
    void 주입후보_포함() {
        ScoredCandidate time = candidate("L1", "A", "B");
        ScoredCandidate injected = candidate("L2", "C", "D");

        Map<String, List<Edge>> map = RouteSearchService.edgesBySignature(
                List.of(time), List.of(), List.of(injected));

        assertEquals(List.of(injected.path().edges().get(0)),
                map.get(RouteCandidateFinder.exactSignature(injected.response())));
        assertNotNull(map.get(RouteCandidateFinder.exactSignature(time.response())));
    }

    @Test
    @DisplayName("주입 후보가 없으면 시간·혼잡 후보만 들어간다")
    void 주입없음() {
        ScoredCandidate time = candidate("L1", "A", "B");
        ScoredCandidate calm = candidate("L2", "C", "D");

        Map<String, List<Edge>> map = RouteSearchService.edgesBySignature(
                List.of(time), List.of(calm), List.of());

        assertNotNull(map.get(RouteCandidateFinder.exactSignature(time.response())));
        assertNotNull(map.get(RouteCandidateFinder.exactSignature(calm.response())));
        assertNull(map.get("없는서명"));
    }
}
