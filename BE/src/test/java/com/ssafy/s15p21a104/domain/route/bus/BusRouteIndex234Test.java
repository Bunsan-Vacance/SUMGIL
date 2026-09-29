package com.ssafy.s15p21a104.domain.route.bus;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder.RouteStop;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class BusRouteIndex234Test {

    private static Map<String, List<RouteStop>> routes() {
        return Map.of(
                "108", List.of(
                        new RouteStop("S1", 1, 37.5000, 127.0000),
                        new RouteStop("S2", 2, 37.5000, 127.0050)),
                "143", List.of(
                        new RouteStop("S1", 1, 37.5000, 127.0000),
                        new RouteStop("S2", 2, 37.5000, 127.0050)));
    }

    @Test
    @DisplayName("234-T1: 같은 구간 노선은 인덱스에 함께 담긴다")
    void t1_인덱스_노선목록() {
        BusRouteIndex index = BusRouteIndex.build(routes());

        assertEquals(List.of("108", "143"), index.routesFor("S1", "S2"));
        assertTrue(index.routesFor("S9", "S9").isEmpty());
    }

    @Test
    @DisplayName("234-T2: 정규 엣지는 구간당 1개, routeId는 BUS 고정")
    void t2_정규엣지_1개() {
        List<Edge> edges = BusEdgeBuilder.buildCorridors(routes());

        assertEquals(1, edges.size());
        assertEquals("S1", edges.get(0).fromNode());
        assertEquals("S2", edges.get(0).toNode());
        assertEquals(BusEdgeBuilder.BUS_CORRIDOR_ROUTE_ID, edges.get(0).routeId());
        assertTrue(edges.get(0).travelSec() > 0);
    }

    @Test
    @DisplayName("234-T3: optionsFor는 정규 엣지에서 인덱스를, 일반 엣지에서 routeId를 돌려준다")
    void t3_optionsFor_폴백() {
        BusRouteIndex index = BusRouteIndex.build(routes());
        Edge canonical = BusEdgeBuilder.buildCorridors(routes()).get(0);
        Edge legacy = new Edge("S1", "S2", "B100", 60, 0,
                com.ssafy.s15p21a104.domain.route.entity.TravelMode.BUS);

        assertEquals(java.util.Set.of("108", "143"), BusRouteIndex.optionsFor(canonical, index));
        assertEquals(java.util.Set.of("B100"), BusRouteIndex.optionsFor(legacy, null));
        assertEquals(java.util.Set.of("B100"), BusRouteIndex.optionsFor(legacy, index));
    }
}
