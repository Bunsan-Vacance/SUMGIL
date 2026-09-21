package com.ssafy.s15p21a104.domain.route.scoring;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder.RouteStop;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.KShortestPathFinder;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-216 혼잡 비용 모델.
 * 비용 = travelSec * (1 + λ * max(0, level - 100) / 100).
 */
class CongestionCostModelTest {

    private static final Map<String, Double> LEVELS = Map.of(
            "L1", 200.0,
            "L2", 50.0,
            "108", 150.0,
            "143", 40.0);

    private KShortestPathFinder.EdgeCostModel model(double lambda) {
        BusRouteIndex index = BusRouteIndex.build(Map.of(
                "108", List.of(
                        new RouteStop("S1", 1, 37.5000, 127.0000),
                        new RouteStop("S2", 2, 37.5000, 127.0050)),
                "143", List.of(
                        new RouteStop("S1", 1, 37.5000, 127.0000),
                        new RouteStop("S2", 2, 37.5000, 127.0050))));
        return CongestionCostModel.of(lambda, (type, id) -> LEVELS.get(id), index);
    }

    @Test
    @DisplayName("216-C1: 정원 초과분만 체감 배율로 얹는다")
    void c1_초과분만가중() {
        KShortestPathFinder.EdgeCostModel model = model(0.5);

        // L1 level 200 → 600 * 1.5 = 900.
        assertEquals(900, model.travelCost(new Edge("A", "B", "L1", 600, 0, TravelMode.SUBWAY)));
        // L2 level 50 → 그대로 600.
        assertEquals(600, model.travelCost(new Edge("A", "B", "L2", 600, 0, TravelMode.SUBWAY)));
    }

    @Test
    @DisplayName("216-C2: 결측·비대중교통은 시간 비용 그대로다")
    void c2_결측과비주행그대로() {
        KShortestPathFinder.EdgeCostModel model = model(0.5);

        assertEquals(600, model.travelCost(new Edge("A", "B", "L9", 600, 0, TravelMode.SUBWAY)));
        assertEquals(300, model.travelCost(new Edge("A", "B", "WALK", 300, 0, TravelMode.WALK)));
        assertEquals(300, model.travelCost(new Edge("A", "B", "BIKE", 300, 0, TravelMode.BIKE)));
    }

    @Test
    @DisplayName("216-C3: corridor는 옵션 중 가장 덜 붐비는 노선을 탄다고 본다")
    void c3_corridor최소옵션() {
        KShortestPathFinder.EdgeCostModel model = model(0.5);
        Edge corridor = BusEdgeBuilder.buildCorridors(Map.of(
                "108", List.of(
                        new RouteStop("S1", 1, 37.5000, 127.0000),
                        new RouteStop("S2", 2, 37.5000, 127.0050)),
                "143", List.of(
                        new RouteStop("S1", 1, 37.5000, 127.0000),
                        new RouteStop("S2", 2, 37.5000, 127.0050)))).get(0);

        // 옵션 108(150)·143(40) 중 최소 40 → 100 미만이라 그대로.
        assertEquals(corridor.travelSec(), model.travelCost(corridor));
    }

    @Test
    @DisplayName("216-C4: λ=0이면 전부 시간 비용과 같다")
    void c4_람다0동일() {
        KShortestPathFinder.EdgeCostModel model = model(0.0);

        assertEquals(600, model.travelCost(new Edge("A", "B", "L1", 600, 0, TravelMode.SUBWAY)));
    }

    @Test
    @DisplayName("216-C5: 가중 임계 경계 — 100은 무가중, 초과만 가중 (생략 판정 기준)")
    void c5_임계경계() {
        assertFalse(CongestionCostModel.hasWeightEffect(100.0));
        assertFalse(CongestionCostModel.hasWeightEffect(91.9));
        assertTrue(CongestionCostModel.hasWeightEffect(100.1));
    }
}
