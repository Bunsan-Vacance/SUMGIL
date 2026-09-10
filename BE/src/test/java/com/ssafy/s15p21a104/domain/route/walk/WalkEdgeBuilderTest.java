package com.ssafy.s15p21a104.domain.route.walk;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder.Stop;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-119 도보 엣지 생성 검증. DB 없이 green.
 */
class WalkEdgeBuilderTest {

    @Test
    @DisplayName("119-T1: 반경 안 쌍은 양방향 WALK 엣지가 생긴다")
    void t119_반경안_양방향() {
        Map<String, Stop> stations = Map.of("S1", new Stop("S1", 37.5000, 127.0000));
        // 약 400m 동쪽.
        Map<String, Stop> rentals = Map.of("R1", new Stop("R1", 37.5000, 127.0045));

        List<Edge> edges = WalkEdgeBuilder.build(stations, rentals);

        assertEquals(2, edges.size());
        assertTrue(edges.stream().allMatch(e -> e.mode() == TravelMode.WALK));
        assertTrue(edges.stream().allMatch(e -> e.routeId().equals(WalkEdgeBuilder.WALK_ROUTE_ID)));
        assertTrue(edges.stream().anyMatch(e -> e.fromNode().equals("S1") && e.toNode().equals("R1")));
        assertTrue(edges.stream().anyMatch(e -> e.fromNode().equals("R1") && e.toNode().equals("S1")));
    }

    @Test
    @DisplayName("119-T2: 반경 밖 쌍은 엣지가 없다")
    void t119_반경밖_제외() {
        Map<String, Stop> stations = Map.of("S1", new Stop("S1", 37.5000, 127.0000));
        // 약 600m 동쪽 (WALK 반경 500m 밖, BIKE 반경 안).
        Map<String, Stop> rentals = Map.of("R1", new Stop("R1", 37.5000, 127.0068));

        assertTrue(WalkEdgeBuilder.build(stations, rentals).isEmpty());
    }

    @Test
    @DisplayName("119-T3: 소요시간은 거리/도보 속도다")
    void t119_소요시간_산식() {
        Map<String, Stop> stations = Map.of("S1", new Stop("S1", 37.5000, 127.0000));
        Map<String, Stop> rentals = Map.of("R1", new Stop("R1", 37.5000, 127.0045));

        List<Edge> edges = WalkEdgeBuilder.build(stations, rentals);

        double dist = WalkEdgeBuilder.distanceM(
                new Stop("S1", 37.5000, 127.0000), new Stop("R1", 37.5000, 127.0045));
        int expected = (int) Math.round(dist / WalkEdgeBuilder.METERS_PER_SEC);
        assertTrue(expected > 0);
        assertTrue(edges.stream().allMatch(e -> e.travelSec() == expected));
        assertTrue(edges.stream().allMatch(e -> e.waitSec() == 0));
    }

    @Test
    @DisplayName("119-T4: 좌표 없는 정점은 제외한다")
    void t119_좌표없음_제외() {
        Map<String, Stop> stations = Map.of(
                "S1", new Stop("S1", 37.5000, 127.0000),
                "S2", new Stop("S2", null, null));
        Map<String, Stop> rentals = Map.of("R1", new Stop("R1", 37.5000, 127.0045));

        List<Edge> edges = WalkEdgeBuilder.build(stations, rentals);

        assertEquals(2, edges.size());
        assertTrue(edges.stream().noneMatch(e ->
                e.fromNode().equals("S2") || e.toNode().equals("S2")));
    }
}
