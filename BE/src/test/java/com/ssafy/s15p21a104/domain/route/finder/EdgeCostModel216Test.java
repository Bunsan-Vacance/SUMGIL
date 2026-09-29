package com.ssafy.s15p21a104.domain.route.finder;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;

import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-216 혼잡 가중 탐색 RED.
 * 엣지 비용 훅으로 시간 탐색과 다른 경로를 내고, λ=0이면 시간 탐색과 같아야 한다.
 */
class EdgeCostModel216Test {

    private static final Map<String, Double> LEVELS = Map.of("L1", 200.0, "L2", 0.0);

    private RouteGraph graph() {
        return graphOf(
                subway("A", "B", "L1", 100),
                subway("A", "X", "L2", 60),
                subway("X", "B", "L2", 60));
    }

    private KShortestPathFinder.EdgeCostModel time() {
        return KShortestPathFinder.EdgeCostModel.TIME;
    }

    private KShortestPathFinder.EdgeCostModel congested(double lambda) {
        return edge -> {
            Double level = LEVELS.get(edge.routeId());
            if (level == null) {
                return edge.travelSec();
            }
            return Math.round(edge.travelSec() * (1 + lambda * Math.max(0, level - 100) / 100));
        };
    }

    @Test
    @DisplayName("216-T1: 혼잡 가중 탐색은 시간 최단과 다른 경로를 낸다")
    void t1_혼잡탐색_다른경로() {
        var finder = new KShortestPathFinder(new TransferRule(180));

        List<FoundPath> time = finder.findK(graph(), "A", "B", 3, null, null, time());
        List<FoundPath> calm = finder.findK(graph(), "A", "B", 3, null, null, congested(0.5));

        // 시간 탐색은 L1 직통(100), 혼잡 탐색은 L2 경유(120, 가중 120 < 150).
        assertEquals("L1", time.get(0).edges().get(0).routeId());
        assertEquals("L2", calm.get(0).edges().get(0).routeId());
        assertNotEquals(
                time.get(0).edges().stream().map(e -> e.routeId()).toList(),
                calm.get(0).edges().stream().map(e -> e.routeId()).toList());
    }

    @Test
    @DisplayName("216-T2: λ=0이면 혼잡 탐색이 시간 탐색과 같다 (하위호환)")
    void t2_람다0_시간과동일() {
        var finder = new KShortestPathFinder(new TransferRule(180));

        List<FoundPath> time = finder.findK(graph(), "A", "B", 3, null, null, time());
        List<FoundPath> zero = finder.findK(graph(), "A", "B", 3, null, null, congested(0.0));

        assertEquals(
                time.get(0).edges().stream().map(e -> e.routeId()).toList(),
                zero.get(0).edges().stream().map(e -> e.routeId()).toList());
    }
}
