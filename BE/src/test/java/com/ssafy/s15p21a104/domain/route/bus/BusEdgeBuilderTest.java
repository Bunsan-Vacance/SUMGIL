package com.ssafy.s15p21a104.domain.route.bus;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder.RouteStop;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-121 버스 엣지 생성 검증. DB 없이 green.
 */
class BusEdgeBuilderTest {

    private static Map<String, List<RouteStop>> route(String routeId, RouteStop... stops) {
        return Map.of(routeId, List.of(stops));
    }

    @Test
    @DisplayName("121-T1: 순번 정렬 후 인접 정류소가 방향성 BUS 엣지로 이어진다")
    void t121_순번인접_방향성() {
        Map<String, List<RouteStop>> routes = route("R100",
                new RouteStop("S3", 3, 37.5000, 127.0045),
                new RouteStop("S1", 1, 37.5000, 127.0000),
                new RouteStop("S2", 2, 37.5000, 127.0022));

        List<Edge> edges = BusEdgeBuilder.build(routes);

        assertEquals(2, edges.size());
        assertTrue(edges.stream().allMatch(e -> e.mode() == TravelMode.BUS));
        assertTrue(edges.stream().allMatch(e -> e.routeId().equals("R100")));
        assertTrue(edges.stream().anyMatch(e -> e.fromNode().equals("S1") && e.toNode().equals("S2")));
        assertTrue(edges.stream().anyMatch(e -> e.fromNode().equals("S2") && e.toNode().equals("S3")));
    }

    @Test
    @DisplayName("121-T2: 결번이 있어도 정렬 후 인접 연결한다")
    void t121_결번_인접연결() {
        Map<String, List<RouteStop>> routes = route("R100",
                new RouteStop("S1", 1, 37.5000, 127.0000),
                new RouteStop("S3", 3, 37.5000, 127.0045));

        List<Edge> edges = BusEdgeBuilder.build(routes);

        assertEquals(1, edges.size());
        assertEquals("S1", edges.get(0).fromNode());
        assertEquals("S3", edges.get(0).toNode());
    }

    @Test
    @DisplayName("121-T3: 소요시간은 거리/버스 실효 속도다")
    void t121_소요시간_산식() {
        Map<String, List<RouteStop>> routes = route("R100",
                new RouteStop("S1", 1, 37.5000, 127.0000),
                new RouteStop("S2", 2, 37.5000, 127.0045));

        List<Edge> edges = BusEdgeBuilder.build(routes);

        double dist = BusEdgeBuilder.distanceM(
                new RouteStop("S1", 1, 37.5000, 127.0000),
                new RouteStop("S2", 2, 37.5000, 127.0045));
        int expected = (int) Math.round(dist / BusEdgeBuilder.METERS_PER_SEC);
        assertTrue(expected > 0);
        assertTrue(edges.stream().allMatch(e -> e.travelSec() == expected));
        assertTrue(edges.stream().allMatch(e -> e.waitSec() == 0));
    }

    @Test
    @DisplayName("121-T5: 버스 실효 속도는 14km/h다 (네이버 표본 12분/8분 보정, 바꾸면 실측 근거 필요)")
    void t121_실효속도_고정() {
        assertEquals(14_000.0 / 3600.0, BusEdgeBuilder.METERS_PER_SEC, 1e-9);
    }

    @Test
    @DisplayName("121-T4: 좌표 없는 정류소 구간은 제외한다")
    void t121_좌표없음_제외() {
        Map<String, List<RouteStop>> routes = route("R100",
                new RouteStop("S1", 1, 37.5000, 127.0000),
                new RouteStop("S2", 2, null, null),
                new RouteStop("S3", 3, 37.5000, 127.0045));

        List<Edge> edges = BusEdgeBuilder.build(routes);

        assertTrue(edges.isEmpty());
    }
}
