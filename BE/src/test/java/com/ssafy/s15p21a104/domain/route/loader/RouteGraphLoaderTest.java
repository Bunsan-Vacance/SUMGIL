package com.ssafy.s15p21a104.domain.route.loader;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.global.exception.DomainException;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link RouteGraphLoader} 조립 로직 테스트. DB·Redis 없이 수행한다.
 *
 * <p>fixture 요건: 양방향 구간 1개 이상 · 단방향 구간 1개 이상 ·
 * 서로 다른 route_id 2개가 한 역에 걸친 경우 1개 이상.
 */
class RouteGraphLoaderTest {

    /**
     * 정의서 골든 예시 입력(대표 슬롯 필터 후).
     */
    private static RouteGraphRawData goldenRawData() {
        return new RouteGraphRawData(
                List.of(
                        new RouteEdgeRow("st_A", "st_B", "L2", 120, 0),
                        new RouteEdgeRow("st_B", "st_A", "L2", 120, 0),
                        new RouteEdgeRow("st_B", "st_C", "L9", 90, 0)),
                Map.of("st_A", "A역", "st_B", "B역", "st_C", "C역"),
                Map.of("L2", "2호선", "L9", "9호선"));
    }

    @Test
    @DisplayName("94-T1: 골든 예시 입력이면 정점 3·엣지 3이다")
    void T1_골든예시_정점3_엣지3() {
        RouteGraphLoader.LoadResult result = RouteGraphLoader.load(goldenRawData());

        assertEquals(3, result.graph().nodeCount());
        assertEquals(3, result.graph().edgeCount());
        assertEquals(Set.of("st_A", "st_B", "st_C"), result.graph().nodes());
    }

    @Test
    @DisplayName("94-T2: 동일 route_id 양방향 2행이면 엣지 2개이다")
    void T2_양방향2행_엣지2개() {
        RouteGraphRawData rawData = new RouteGraphRawData(
                List.of(
                        new RouteEdgeRow("st_A", "st_B", "L2", 120, 0),
                        new RouteEdgeRow("st_B", "st_A", "L2", 120, 0)),
                Map.of(),
                Map.of());

        RouteGraph graph = RouteGraphLoader.load(rawData).graph();

        assertEquals(2, graph.edgeCount());
        assertTrue(graph.findEdge("st_A", "st_B").isPresent());
        assertTrue(graph.findEdge("st_B", "st_A").isPresent());
    }

    @Test
    @DisplayName("94-T3: 단방향 1행 구간이면 엣지 1개이고 역방향이 없다")
    void T3_단방향1행_엣지1개_역방향없음() {
        RouteGraphRawData rawData = new RouteGraphRawData(
                List.of(new RouteEdgeRow("st_B", "st_C", "L9", 90, 0)),
                Map.of(),
                Map.of());

        RouteGraph graph = RouteGraphLoader.load(rawData).graph();

        assertEquals(2, graph.nodeCount());
        assertEquals(1, graph.edgeCount());
        assertTrue(graph.findEdge("st_B", "st_C").isPresent());
        assertTrue(graph.findEdge("st_C", "st_B").isEmpty());
        assertTrue(graph.outgoingEdges("st_C").isEmpty());
    }

    @Test
    @DisplayName("94-T4: st_B의 소속 노선은 엣지 routeId에서 파생된 {L2, L9}이다")
    void T4_소속노선_엣지에서파생() {
        RouteGraph graph = RouteGraphLoader.load(goldenRawData()).graph();

        assertEquals(Set.of("L2", "L9"), graph.linesOfStation("st_B"));
        assertEquals(Set.of("L9"), graph.linesOfStation("st_C"));
        assertEquals(Set.of("L2"), graph.linesOfStation("st_A"));
    }

    @Test
    @DisplayName("94-T5: 미등록 역 ID 조회는 부재를 정확히 보고한다")
    void T5_미등록역ID_부재보고() {
        RouteGraphLoader.LoadResult result = RouteGraphLoader.load(goldenRawData());

        assertTrue(result.nameMapper().stationNameOf("st_UNKNOWN").isEmpty());
        assertTrue(result.graph().linesOfStation("st_UNKNOWN").isEmpty());
        assertTrue(!result.graph().containsNode("st_UNKNOWN"));
        assertTrue(result.graph().outgoingEdges("st_UNKNOWN").isEmpty());
        assertTrue(result.graph().findEdge("st_UNKNOWN", "st_A").isEmpty());
        assertTrue(result.graph().findEdge("st_A", "st_UNKNOWN").isEmpty());
    }

    @Test
    @DisplayName("94-T6: SUBWAY 0행이면 명확한 예외로 실패한다")
    void T6_빈입력_명확한예외() {
        RouteGraphRawData emptyRows = new RouteGraphRawData(List.of(), Map.of(), Map.of());

        assertThrows(DomainException.class, () -> RouteGraphLoader.load(emptyRows));
        assertThrows(DomainException.class,
                () -> RouteGraphLoader.load(new RouteGraphRawData(null, Map.of(), Map.of())));
    }

    @Test
    @DisplayName("94-T7: 로드 후 그래프는 불변이다(수정 시도 차단)")
    void T7_로드후_불변() {
        RouteGraph graph = RouteGraphLoader.load(goldenRawData()).graph();

        assertThrows(UnsupportedOperationException.class, () -> graph.nodes().add("st_X"));
        assertThrows(UnsupportedOperationException.class,
                () -> graph.adjacency().put("st_X", List.of()));
        assertThrows(UnsupportedOperationException.class,
                () -> graph.outgoingEdges("st_A").add(
                        new com.ssafy.s15p21a104.domain.route.graph.Edge("st_A", "st_X", "L2", 1, 0,
                                TravelMode.SUBWAY)));
        assertThrows(UnsupportedOperationException.class,
                () -> graph.linesOfStation("st_B").add("L1"));
        assertThrows(UnsupportedOperationException.class,
                () -> graph.edges().add(
                        new com.ssafy.s15p21a104.domain.route.graph.Edge("st_A", "st_X", "L2", 1, 0,
                                TravelMode.SUBWAY)));
    }

    @Test
    @DisplayName("94-T1(보조): 골든 예시에 직접 엣지 st_A→st_C는 없고 이름 매핑이 동작한다")
    void T1보조_직접엣지없음_이름매핑() {
        RouteGraphLoader.LoadResult result = RouteGraphLoader.load(goldenRawData());

        assertTrue(result.graph().findEdge("st_A", "st_C").isEmpty());
        assertEquals("A역", result.nameMapper().stationNameOf("st_A").orElseThrow());
        assertEquals("2호선", result.nameMapper().lineNameOf("L2").orElseThrow());
        assertTrue(result.nameMapper().lineNameOf("L_UNKNOWN").isEmpty());
    }

    @Test
    @DisplayName("109-T5: 추가 엣지가 같은 규칙으로 합쳐진다")
    void T109_추가엣지_병합() {
        RouteGraph graph = RouteGraphLoader.load(goldenRawData(), List.of(
                        new com.ssafy.s15p21a104.domain.route.graph.Edge(
                                "st_A", "R1", "BIKE", 240, 0, TravelMode.BIKE)))
                .graph();

        assertEquals(4, graph.edgeCount());
        assertTrue(graph.findEdge("st_A", "R1").isPresent());
        assertEquals(TravelMode.BIKE, graph.findEdge("st_A", "R1").orElseThrow().mode());
        assertTrue(graph.nodes().contains("R1"));
    }

    @Test
    @DisplayName("109-T6: 추가 엣지 없이 기존 호출은 그대로 동작한다")
    void T109_추가없음_기존동일() {
        RouteGraph graph = RouteGraphLoader.load(goldenRawData(), List.of()).graph();

        assertEquals(3, graph.edgeCount());
    }
}
