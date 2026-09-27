package com.ssafy.s15p21a104.domain.route.bike;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder.Stop;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-122 대여소↔대여소 BIKE 직접 간선 검증. DB 없이 green.
 */
class BikeRentalEdgeBuilderTest {

    @Test
    @DisplayName("122-T1: 반경 안 대여소 쌍은 양방향 BIKE 엣지가 생긴다")
    void t122_반경안_양방향() {
        // 약 400m 동쪽.
        Map<String, Stop> rentals = Map.of(
                "R1", new Stop("R1", 37.5000, 127.0000),
                "R2", new Stop("R2", 37.5000, 127.0045));

        List<Edge> edges = BikeRentalEdgeBuilder.build(rentals);

        assertEquals(2, edges.size());
        assertTrue(edges.stream().allMatch(e -> e.mode() == TravelMode.BIKE));
        assertTrue(edges.stream().allMatch(e -> e.routeId().equals(BikeEdgeBuilder.BIKE_ROUTE_ID)));
        assertTrue(edges.stream().anyMatch(e -> e.fromNode().equals("R1") && e.toNode().equals("R2")));
        assertTrue(edges.stream().anyMatch(e -> e.fromNode().equals("R2") && e.toNode().equals("R1")));
    }

    @Test
    @DisplayName("122-T2: 반경 밖 쌍은 엣지가 없다")
    void t122_반경밖_제외() {
        // 약 2km 동쪽.
        Map<String, Stop> rentals = Map.of(
                "R1", new Stop("R1", 37.5000, 127.0000),
                "R2", new Stop("R2", 37.5000, 127.0227));

        assertTrue(BikeRentalEdgeBuilder.build(rentals).isEmpty());
    }

    @Test
    @DisplayName("122-T3: 소요시간은 거리/자전거 속도이며 역 엣지는 만들지 않는다")
    void t122_소요시간_산식_역제외() {
        Map<String, Stop> rentals = Map.of(
                "R1", new Stop("R1", 37.5000, 127.0000),
                "R2", new Stop("R2", 37.5000, 127.0045));

        List<Edge> edges = BikeRentalEdgeBuilder.build(rentals);

        double dist = BikeEdgeBuilder.distanceM(
                new Stop("R1", 37.5000, 127.0000), new Stop("R2", 37.5000, 127.0045));
        int expected = (int) Math.round(dist / (12_000.0 / 3600.0));
        assertTrue(expected > 0);
        assertTrue(edges.stream().allMatch(e -> e.travelSec() == expected));
        assertTrue(edges.stream().allMatch(e -> e.waitSec() == 0));
        assertTrue(edges.stream().noneMatch(e -> e.fromNode().equals("S1") || e.toNode().equals("S1")));
        assertTrue(BikeRentalEdgeBuilder.build(null).isEmpty());
        assertTrue(BikeRentalEdgeBuilder.build(Map.of()).isEmpty());
    }

    @Test
    @DisplayName("G6: 반경 경계 999m는 포함, 1001m는 제외")
    void g6_반경경계_999_1001() {
        // 위도 37.5에서 999m ≈ 0.01132437도, 1001m ≈ 0.01134704도.
        Stop r1 = new Stop("R1", 37.5000, 127.0000);
        Stop inside = new Stop("R2", 37.5000, 127.01132437);
        Stop outside = new Stop("R2", 37.5000, 127.01134704);

        assertTrue(BikeEdgeBuilder.distanceM(r1, inside) <= BikeEdgeBuilder.RADIUS_M);
        assertTrue(BikeEdgeBuilder.distanceM(r1, outside) > BikeEdgeBuilder.RADIUS_M);
        assertEquals(2, BikeRentalEdgeBuilder.build(Map.of("R1", r1, "R2", inside)).size());
        assertTrue(BikeRentalEdgeBuilder.build(Map.of("R1", r1, "R2", outside)).isEmpty());
    }
}
