package com.ssafy.s15p21a104.domain.route.finder;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bike;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.walk;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-233 출구 왕복 제거 RED.
 * K-path 대안 후보에 역→대여소→역 즉시 왕복이 올라오면 안 된다.
 */
class TransferRoundtrip233Test {

    private static RouteGraph graph() {
        return graphOf(
                subway("A", "B", "L1", 100),
                walk("B", "R", 29),
                walk("R", "B", 29),
                subway("B", "C", "L2", 50),
                subway("A", "D", "L3", 300),
                subway("D", "C", "L3", 300),
                bike("R", "R2", 200),
                bike("R2", "C", 200));
    }

    private static TransferRule rule() {
        return new TransferRule(180).withTable(Map.of(
                new TransferRule.TransferKey("B", "L1", "L2"), 260));
    }

    @Test
    @DisplayName("233-T1: 직접 환승이 실측 비용으로 이긴다")
    void t1_직접환승_실측승리() {
        FoundPath path = new ShortestPathFinder(rule()).find(graph(), "A", "C");

        assertEquals(List.of("A", "B", "C"), path.stations());
        assertEquals(100 + 50 + 260, path.totalSec());
        assertEquals(1, path.transferCount());
    }

    @Test
    @DisplayName("233-T2: K-path 대안에 즉시 도보 왕복이 없다")
    void t2_대안_왕복없음() {
        List<FoundPath> paths =
                new KShortestPathFinder(rule()).findK(graph(), "A", "C", 5);

        assertTrue(paths.size() >= 2);
        assertNoImmediateRoundtrip(paths);
    }

    @Test
    @DisplayName("233-T3: 0초 왕복 동점도 대안에 올라오지 않는다")
    void t3_제로왕복_동점제외() {
        // R이 B와 동좌표라 왕복 도보가 0초다. 직접 경로와 동점이지만 무의미 루프라 제외한다.
        RouteGraph zeroGraph = graphOf(
                subway("A", "B", "L1", 100),
                walk("B", "R0", 0),
                walk("R0", "B", 0),
                subway("B", "C", "L2", 50),
                subway("A", "D", "L3", 300),
                subway("D", "C", "L3", 300));
        List<FoundPath> paths =
                new KShortestPathFinder(rule()).findK(zeroGraph, "A", "C", 5);

        assertTrue(paths.size() >= 2);
        assertNoImmediateRoundtrip(paths);
    }

    private static void assertNoImmediateRoundtrip(List<FoundPath> paths) {
        for (FoundPath path : paths) {
            List<String> stations = path.stations();
            for (int i = 0; i + 2 < stations.size(); i++) {
                assertTrue(!stations.get(i).equals(stations.get(i + 2)),
                        "즉시 왕복 검출: " + stations);
            }
        }
    }
}
