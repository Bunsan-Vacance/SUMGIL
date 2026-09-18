package com.ssafy.s15p21a104.domain.route.finder;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder.RouteStop;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class BusCorridor234Test {

    private static Map<String, List<RouteStop>> busRoutes() {
        return Map.of(
                "108", List.of(
                        new RouteStop("S1", 1, 37.5000, 127.0000),
                        new RouteStop("S2", 2, 37.5000, 127.0050)),
                "143", List.of(
                        new RouteStop("S1", 1, 37.5000, 127.0000),
                        new RouteStop("S2", 2, 37.5000, 127.0050)));
    }

    private static RouteGraph corridorGraph() {
        List<Edge> edges = new java.util.ArrayList<>();
        edges.add(new Edge("A", "S1", "WALK", 60, 0, TravelMode.WALK));
        edges.addAll(BusEdgeBuilder.buildCorridors(busRoutes()));
        edges.add(new Edge("S2", "C", "WALK", 60, 0, TravelMode.WALK));
        return graphOf(edges.toArray(new Edge[0]));
    }

    private static Map<String, com.ssafy.s15p21a104.domain.route.mapper.RouteMapper.StationInfo> infos() {
        return Map.of(
                "A", new com.ssafy.s15p21a104.domain.route.mapper.RouteMapper.StationInfo(
                        "A", "A", 37.5, 127.0),
                "S1", new com.ssafy.s15p21a104.domain.route.mapper.RouteMapper.StationInfo(
                        "S1", "S1", 37.5, 127.0),
                "S2", new com.ssafy.s15p21a104.domain.route.mapper.RouteMapper.StationInfo(
                        "S2", "S2", 37.5, 127.0),
                "C", new com.ssafy.s15p21a104.domain.route.mapper.RouteMapper.StationInfo(
                        "C", "C", 37.5, 127.0));
    }

    @Test
    @DisplayName("234-T20: 정규 구간은 K-path 1슬롯만 차지한다")
    void t20_정규구간_단일슬롯() {
        BusRouteIndex index = BusRouteIndex.build(busRoutes());
        RouteCandidateFinder finder = new RouteCandidateFinder(
                new TransferRule(180), Map.of(), java.util.Set.of(), infos(), Map::of, index);

        List<com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse> out =
                finder.findCandidates(corridorGraph(), "A", "C", 10);

        assertEquals(1, out.size());
        assertTrue(out.get(0).legs().stream()
                .anyMatch(leg -> leg.mode() == TravelMode.BUS));
    }
}
