package com.ssafy.s15p21a104.domain.route.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.FoundPath;
import com.ssafy.s15p21a104.domain.route.finder.ShortestPathFinder;
import com.ssafy.s15p21a104.domain.route.loader.RouteEdgeRow;
import com.ssafy.s15p21a104.domain.route.loader.RouteGraphLoader;
import com.ssafy.s15p21a104.domain.route.loader.RouteGraphRawData;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-107 수단 구분 단위 테스트. DB·Redis 없이 수행한다.
 */
class EdgeModeTest {

    @Test
    @DisplayName("107-T1 로더 SUBWAY 고정·탐색 결과 동일 (AC1)")
    void t1_로더SUBWAY_탐색동일() {
        RouteGraphRawData rawData = new RouteGraphRawData(
                List.of(
                        new RouteEdgeRow("A", "B", "L1", 100, 0),
                        new RouteEdgeRow("B", "C", "L1", 100, 0)),
                Map.of(),
                Map.of());

        RouteGraph graph = RouteGraphLoader.load(rawData).graph();

        // 로더가 mode를 버리지 않고 SUBWAY로 싣는다.
        assertEquals(3, graph.nodeCount());
        assertEquals(2, graph.edgeCount());
        assertTrue(graph.edges().stream().allMatch(edge -> edge.mode() == TravelMode.SUBWAY));

        // 탐색 값·순서가 이전과 동일하다.
        FoundPath path = new ShortestPathFinder(new TransferRule(180)).find(graph, "A", "C");

        assertEquals(List.of("A", "B", "C"), path.stations());
        assertEquals(200, path.totalSec());
        assertEquals(0, path.transferCount());
        assertEquals(List.of("L1", "L1"), path.edges().stream().map(Edge::routeId).toList());
        assertTrue(path.edges().stream().allMatch(edge -> edge.mode() == TravelMode.SUBWAY));
    }

    @Test
    @DisplayName("107-T2 BIKE 엣지 mode 전파·비용 미사용 (AC2)")
    void t2_BIKE_mode전파_비용미사용() {
        RouteGraph graph = graphOf(
                new Edge("A", "B", "B1", 100, 0, TravelMode.BIKE),
                new Edge("B", "C", "L1", 50, 0, TravelMode.SUBWAY));

        // 그래프가 mode를 그대로 보관한다.
        assertEquals(TravelMode.BIKE, graph.findEdge("A", "B").orElseThrow().mode());
        assertEquals(TravelMode.SUBWAY, graph.findEdge("B", "C").orElseThrow().mode());

        // 탐색은 mode를 비용에 쓰지 않고(routeId 기준) 엣지를 그대로 돌려준다.
        FoundPath path = new ShortestPathFinder(new TransferRule(180)).find(graph, "A", "C");

        assertEquals(List.of("A", "B", "C"), path.stations());
        assertEquals(100 + 50 + 180, path.totalSec());
        assertEquals(1, path.transferCount());
        assertEquals(List.of(TravelMode.BIKE, TravelMode.SUBWAY),
                path.edges().stream().map(Edge::mode).toList());
    }

    private static RouteGraph graphOf(Edge... edges) {
        Set<String> nodes = new HashSet<>();
        Map<String, List<Edge>> adjacency = new HashMap<>();
        Map<String, Set<String>> lines = new HashMap<>();
        for (Edge edge : edges) {
            nodes.add(edge.fromNode());
            nodes.add(edge.toNode());
            adjacency.computeIfAbsent(edge.fromNode(), key -> new ArrayList<>()).add(edge);
            lines.computeIfAbsent(edge.fromNode(), key -> new HashSet<>()).add(edge.routeId());
            lines.computeIfAbsent(edge.toNode(), key -> new HashSet<>()).add(edge.routeId());
        }
        return RouteGraph.of(nodes, adjacency, lines);
    }
}
