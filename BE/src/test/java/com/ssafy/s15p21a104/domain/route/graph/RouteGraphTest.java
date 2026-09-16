package com.ssafy.s15p21a104.domain.route.graph;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link RouteGraph#filterByModes} 단위 테스트(S15P21A104-185).
 *
 * <p>허용 수단 조합별 대체 후보 탐색이 최단경로 알고리즘을 바꾸지 않고, 하위 그래프만
 * 새로 만들어 같은 알고리즘을 재사용한다는 전제를 검증한다.
 */
class RouteGraphTest {

    private RouteGraph graphOf(Edge... edges) {
        Set<String> nodes = new HashSet<>();
        Map<String, List<Edge>> adjacency = new HashMap<>();
        Map<String, Set<String>> lines = new HashMap<>();
        for (Edge edge : edges) {
            nodes.add(edge.fromNode());
            nodes.add(edge.toNode());
            adjacency.computeIfAbsent(edge.fromNode(), key -> new java.util.ArrayList<>()).add(edge);
            lines.computeIfAbsent(edge.fromNode(), key -> new HashSet<>()).add(edge.routeId());
            lines.computeIfAbsent(edge.toNode(), key -> new HashSet<>()).add(edge.routeId());
        }
        return RouteGraph.of(nodes, adjacency, lines);
    }

    @Test
    @DisplayName("허용 수단 밖 엣지는 제외되고, 그 엣지에만 있던 정점도 사라진다")
    void 허용_수단만_남긴다() {
        RouteGraph graph = graphOf(
                new Edge("A", "B", "L1", 100, 0, TravelMode.SUBWAY),
                new Edge("B", "R1", "BIKE", 50, 0, TravelMode.BIKE));

        RouteGraph filtered = graph.filterByModes(Set.of(TravelMode.SUBWAY));

        assertEquals(1, filtered.edgeCount());
        assertTrue(filtered.containsNode("A"));
        assertTrue(filtered.containsNode("B"));
        assertFalse(filtered.containsNode("R1"));
    }

    @Test
    @DisplayName("허용 수단이 여러 개면 해당하는 엣지를 모두 남긴다")
    void 여러_수단_허용() {
        RouteGraph graph = graphOf(
                new Edge("A", "B", "L1", 100, 0, TravelMode.SUBWAY),
                new Edge("B", "C", "B100", 60, 0, TravelMode.BUS),
                new Edge("C", "D", "BIKE", 40, 0, TravelMode.BIKE));

        RouteGraph filtered = graph.filterByModes(Set.of(TravelMode.SUBWAY, TravelMode.BUS));

        assertEquals(2, filtered.edgeCount());
        assertTrue(filtered.containsNode("C"));
        assertFalse(filtered.containsNode("D"));
    }

    @Test
    @DisplayName("해당 수단 엣지가 하나도 없으면 빈 그래프가 된다")
    void 해당_수단_없으면_빈그래프() {
        RouteGraph graph = graphOf(new Edge("A", "B", "L1", 100, 0, TravelMode.SUBWAY));

        RouteGraph filtered = graph.filterByModes(Set.of(TravelMode.BIKE));

        assertEquals(0, filtered.nodeCount());
        assertEquals(0, filtered.edgeCount());
    }

    @Test
    @DisplayName("원본 그래프는 바뀌지 않는다")
    void 원본은_불변() {
        RouteGraph graph = graphOf(
                new Edge("A", "B", "L1", 100, 0, TravelMode.SUBWAY),
                new Edge("B", "C", "BIKE", 50, 0, TravelMode.BIKE));

        graph.filterByModes(Set.of(TravelMode.SUBWAY));

        assertEquals(2, graph.edgeCount());
        assertTrue(graph.containsNode("C"));
    }

    /**
     * {@link RouteGraph#withExtraEdges} 단위 테스트(S15P21A104-187, 좌표 접근 임시 간선).
     */
    @Test
    @DisplayName("추가 엣지가 있으면 새 정점·엣지가 합쳐진 그래프를 돌려준다")
    void withExtraEdges_추가엣지_합쳐짐() {
        RouteGraph graph = graphOf(new Edge("A", "B", "L1", 100, 0, TravelMode.SUBWAY));

        RouteGraph extended = graph.withExtraEdges(
                List.of(new Edge("PLACE", "A", "WALK", 30, 0, TravelMode.WALK)));

        assertEquals(2, extended.edgeCount());
        assertTrue(extended.containsNode("PLACE"));
        assertTrue(extended.findEdge("PLACE", "A").isPresent());
    }

    @Test
    @DisplayName("withExtraEdges는 원본 그래프를 바꾸지 않는다")
    void withExtraEdges_원본은_불변() {
        RouteGraph graph = graphOf(new Edge("A", "B", "L1", 100, 0, TravelMode.SUBWAY));

        graph.withExtraEdges(List.of(new Edge("PLACE", "A", "WALK", 30, 0, TravelMode.WALK)));

        assertEquals(1, graph.edgeCount());
        assertFalse(graph.containsNode("PLACE"));
    }

    @Test
    @DisplayName("추가 엣지가 없으면(null·빈 목록) 같은 내용의 그래프를 그대로 돌려준다")
    void withExtraEdges_빈목록_변화없음() {
        RouteGraph graph = graphOf(new Edge("A", "B", "L1", 100, 0, TravelMode.SUBWAY));

        assertEquals(1, graph.withExtraEdges(List.of()).edgeCount());
        assertEquals(1, graph.withExtraEdges(null).edgeCount());
    }
}
