package com.ssafy.s15p21a104.domain.route.finder;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bus;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-213 T2 탐색 1회 RED.
 * 단일 그래프 1회 탐색으로 서로 다른 K개 후보를 낸다.
 */
class KShortestPathFinder213Test {

    private final KShortestPathFinder finder = new KShortestPathFinder(new TransferRule(180));

    @Test
    @DisplayName("213-T2: 두 경로 그래프에서 K=2면 서로 다른 2개가 나온다")
    void t2_두경로_K2_두후보() {
        RouteGraph graph = graphOf(
                subway("A", "B", "L1", 100),
                subway("B", "C", "L1", 100),
                subway("A", "D", "L2", 150),
                subway("D", "C", "L2", 150));

        List<FoundPath> paths = finder.findK(graph, "A", "C", 2);

        assertEquals(2, paths.size());
        Set<String> signatures = paths.stream()
                .map(p -> p.stations().stream().collect(Collectors.joining(">")))
                .collect(Collectors.toSet());
        assertEquals(Set.of("A>B>C", "A>D>C"), signatures);
        assertTrue(paths.get(0).totalSec() <= paths.get(1).totalSec());
    }

    @Test
    @DisplayName("213-T2: 후보 부족하면 있는 만큼만 나온다")
    void t2_후보부족_있는만큼() {
        RouteGraph graph = graphOf(subway("A", "B", "L1", 100));

        List<FoundPath> paths = finder.findK(graph, "A", "B", 5);

        assertEquals(1, paths.size());
    }

    @Test
    @DisplayName("213-T2: K=0이면 빈 목록이다 (경계값)")
    void t2_K0_빈목록() {
        RouteGraph graph = graphOf(subway("A", "B", "L1", 100));

        assertTrue(finder.findK(graph, "A", "B", 0).isEmpty());
    }

    @Test
    @DisplayName("213-T2: 연결 불가면 빈 목록이다 (에러 아님)")
    void t2_연결불가_빈목록() {
        RouteGraph graph = graphOf(
                subway("A", "B", "L1", 100),
                subway("C", "D", "L1", 100));

        assertTrue(finder.findK(graph, "A", "D", 5).isEmpty());
    }

    @Test
    @DisplayName("213-T2: 서로 다른 후보는 leg 서명이 다르다 (중복 없음)")
    void t2_중복없음() {
        RouteGraph graph = graphOf(
                subway("A", "B", "L1", 100),
                subway("B", "C", "L1", 100),
                subway("A", "D", "L2", 150),
                subway("D", "C", "L2", 150));

        List<FoundPath> paths = finder.findK(graph, "A", "C", 10);

        Set<String> signatures = new HashSet<>();
        for (FoundPath path : paths) {
            String sig = path.edges().stream()
                    .map(e -> e.mode() + ":" + e.fromNode() + "->" + e.toNode() + ":" + e.routeId())
                    .collect(Collectors.joining("|"));
            assertTrue(signatures.add(sig), "중복 후보: " + sig);
        }
    }

    @Test
    @DisplayName("234-T56: K경로 BUS 누적 공통 노선 소진 시 환승 위치를 재집계한다")
    void t234_K경로_BUS누적교집합소진_환승재집계() {
        BusRouteIndex index = BusRouteIndex.build(Map.of(
                "108", List.of(
                        new BusEdgeBuilder.RouteStop("A", 1, 37.5000, 127.0000),
                        new BusEdgeBuilder.RouteStop("B", 2, 37.5000, 127.0050),
                        new BusEdgeBuilder.RouteStop("C", 3, 37.5000, 127.0100)),
                "143", List.of(
                        new BusEdgeBuilder.RouteStop("B", 1, 37.5000, 127.0050),
                        new BusEdgeBuilder.RouteStop("C", 2, 37.5000, 127.0100),
                        new BusEdgeBuilder.RouteStop("D", 3, 37.5000, 127.0150))));
        TransferRule rule = new TransferRule(180).withTable(Map.of(
                new TransferRule.TransferKey("B", "108", "BUS"), 500,
                new TransferRule.TransferKey("C", "108", "143"), 240));
        RouteGraph graph = graphOf(
                subway("A", "D", "L1", 50),
                bus("A", "B", BusEdgeBuilder.BUS_CORRIDOR_ROUTE_ID, 100),
                bus("B", "C", BusEdgeBuilder.BUS_CORRIDOR_ROUTE_ID, 100),
                bus("C", "D", BusEdgeBuilder.BUS_CORRIDOR_ROUTE_ID, 100));

        List<FoundPath> paths = new KShortestPathFinder(rule, index).findK(graph, "A", "D", 2);

        assertEquals(2, paths.size());
        assertEquals(List.of("A", "B", "C", "D"), paths.get(1).stations());
        assertEquals(540, paths.get(1).totalSec());
        assertEquals(1, paths.get(1).transferCount());
    }
}
