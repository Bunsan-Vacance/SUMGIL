package com.ssafy.s15p21a104.domain.route.service;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-213 T4 routeName·좌표 접근 분리 RED.
 */
class RouteNameAccess213Test {

    private static RouteSearchResponse responseOf(String mode, String routeId) {
        TravelMode travelMode = TravelMode.valueOf(mode);
        RouteLegResponse leg = new RouteLegResponse(travelMode,
                "A", "에이역", 37.5, 127.0, "C", "씨역", 37.5, 127.01,
                routeId, 5.0, null, "unavailable", null, null, null);
        return new RouteSearchResponse(RouteType.SHORTEST, 5.0, List.of(leg),
                RouteSource.ALGORITHM, null, 0, null);
    }

    @Test
    @DisplayName("213-T4: SUBWAY·BUS에 노선명이 붙고 나머지는 null이다")
    void t4_노선명배치() {
        RouteNameResolver resolver = new RouteNameResolver(
                ids -> Map.of("1002", "2호선"),
                ids -> Map.of("B100", "100번"));

        List<RouteSearchResponse> result = resolver.withRouteNames(List.of(
                responseOf("SUBWAY", "1002"), responseOf("BUS", "B100"), responseOf("BIKE", "BIKE")));

        assertEquals(3, result.size());
        assertEquals("2호선", result.get(0).legs().get(0).routeName());
        assertEquals("100번", result.get(1).legs().get(0).routeName());
        assertEquals(null, result.get(2).legs().get(0).routeName());
    }

    @Test
    @DisplayName("213-T4: 좌표 접근 엣지는 반경 안 가까운 순 최대 5개이다")
    void t4_좌표접근_반경상한() {
        Map<String, RouteMapper.StationInfo> infos = Map.of(
                "S1", new RouteMapper.StationInfo("S1", "역1", 37.5, 127.0),
                "S2", new RouteMapper.StationInfo("S2", "역2", 37.5005, 127.0005),
                "FAR", new RouteMapper.StationInfo("FAR", "먼역", 38.5, 128.0));
        java.util.Set<String> nodes = new java.util.HashSet<>(List.of("S1", "S2", "FAR"));
        com.ssafy.s15p21a104.domain.route.graph.RouteGraph graph =
                com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf(
                        new Edge("S1", "S2", "L1", 100, 0, TravelMode.SUBWAY),
                        new Edge("S2", "S1", "L1", 100, 0, TravelMode.SUBWAY),
                        new Edge("FAR", "FAR", "L9", 10, 0, TravelMode.SUBWAY));

        List<Edge> edges = CoordinateAccessEdges.accessEdges(
                "PLACE-ORIGIN", 37.5, 127.0, infos, graph, true, Set.of("S1", "S2"));

        assertEquals(2, edges.size());
        assertTrue(edges.stream().allMatch(e -> e.fromNode().equals("PLACE-ORIGIN")));
        assertTrue(edges.stream().noneMatch(e -> e.toNode().equals("FAR")));
    }

    private static void assertTrue(boolean value) {
        org.junit.jupiter.api.Assertions.assertTrue(value);
    }
}
