package com.ssafy.s15p21a104.domain.route.finder;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-95 최단 경로 탐색 단위 테스트. 그래프를 직접 조립해 주입하며 DB·Redis가 필요 없다.
 */
class ShortestPathFinderTest {

    private final ShortestPathFinder finder = new ShortestPathFinder(new TransferRule(180));

    @Test
    @DisplayName("95-T1 단일 경로 그래프는 그 경로 1개 (AC1)")
    void t1_단일경로_그대로반환() {
        RouteGraph graph = graphOf(
                edge("A", "B", "L1", 100),
                edge("B", "C", "L1", 100));

        FoundPath path = finder.find(graph, "A", "C");

        assertEquals(List.of("A", "B", "C"), path.stations());
        assertEquals(200, path.totalSec());
        assertEquals(0, path.transferCount());
    }

    @Test
    @DisplayName("95-T2 여러 경로 중 소요시간 최소 경로 (AC1)")
    void t2_여러경로_최소선택() {
        RouteGraph graph = graphOf(
                edge("A", "B", "L1", 100),
                edge("B", "D", "L1", 100),
                edge("A", "C", "L2", 50),
                edge("C", "D", "L2", 60));

        FoundPath path = finder.find(graph, "A", "D");

        assertEquals(List.of("A", "C", "D"), path.stations());
        assertEquals(110, path.totalSec());
        assertEquals(0, path.transferCount());
    }

    @Test
    @DisplayName("95-T3 환승 필요 OD는 횟수 정확·상수 포함 비용 (AC2)")
    void t3_환승_횟수와비용() {
        RouteGraph graph = graphOf(
                edge("A", "B", "L1", 100),
                edge("B", "C", "L2", 50));

        FoundPath path = finder.find(graph, "A", "C");

        assertEquals(List.of("A", "B", "C"), path.stations());
        assertEquals(100 + 50 + 180, path.totalSec());
        assertEquals(1, path.transferCount());
        assertEquals(List.of("L1", "L2"), path.edges().stream().map(Edge::routeId).toList());
    }

    @Test
    @DisplayName("95-T4 같은 노선 유지 OD는 환승 0회 (AC2)")
    void t4_같은노선_환승없음() {
        RouteGraph graph = graphOf(
                edge("A", "B", "L1", 70),
                edge("B", "C", "L1", 80),
                edge("C", "D", "L1", 90));

        FoundPath path = finder.find(graph, "A", "D");

        assertEquals(70 + 80 + 90, path.totalSec());
        assertEquals(0, path.transferCount());
    }

    @Test
    @DisplayName("95-T5 출발=도착이면 SAME_ORIGIN_DEST (AC3)")
    void t5_출발도착같음_오류() {
        RouteGraph graph = graphOf(edge("A", "B", "L1", 100));

        DomainException exception = assertThrows(DomainException.class,
                () -> finder.find(graph, "A", "A"));

        assertEquals(ErrorType.SAME_ORIGIN_DEST, exception.getErrorType());
    }

    @Test
    @DisplayName("95-T6 미등록 역이면 STATION_NOT_FOUND (AC3)")
    void t6_미등록역_오류() {
        RouteGraph graph = graphOf(edge("A", "B", "L1", 100));

        DomainException exception = assertThrows(DomainException.class,
                () -> finder.find(graph, "A", "Z"));

        assertEquals(ErrorType.STATION_NOT_FOUND, exception.getErrorType());
    }

    @Test
    @DisplayName("95-T7 연결 불가면 ROUTE_NOT_FOUND (AC3)")
    void t7_연결불가_오류() {
        RouteGraph graph = graphOf(
                edge("A", "B", "L1", 100),
                edge("C", "D", "L1", 100));

        DomainException exception = assertThrows(DomainException.class,
                () -> finder.find(graph, "A", "D"));

        assertEquals(ErrorType.ROUTE_NOT_FOUND, exception.getErrorType());
    }

    @Test
    @DisplayName("95-T8 사이클 포함 그래프도 재방문 없는 경로 (AC4)")
    void t8_사이클_단순경로() {
        RouteGraph graph = graphOf(
                edge("A", "B", "L1", 10),
                edge("B", "A", "L1", 10),
                edge("B", "C", "L1", 10));

        FoundPath path = finder.find(graph, "A", "C");

        assertEquals(List.of("A", "B", "C"), path.stations());
        assertEquals(20, path.totalSec());
        assertTrue(path.stations().stream().distinct().count() == path.stations().size());
    }

    @Test
    @DisplayName("97-T2 노선 3개 경유 OD는 3구간 경로·환승 2회 (AC1)")
    void t9_세노선_환승2회() {
        RouteGraph graph = graphOf(
                edge("A", "B", "L1", 100),
                edge("B", "C", "L2", 50),
                edge("C", "D", "L3", 60));

        FoundPath path = finder.find(graph, "A", "D");

        assertEquals(List.of("A", "B", "C", "D"), path.stations());
        assertEquals(100 + 50 + 60 + 180 * 2, path.totalSec());
        assertEquals(2, path.transferCount());
        assertEquals(List.of("L1", "L2", "L3"), path.edges().stream().map(Edge::routeId).toList());
    }

    @Test
    @DisplayName("역별 실측이 있으면 그 역 환승에 실측을 쓴다")
    void t_역별실측_환승적용() {
        ShortestPathFinder measured = new ShortestPathFinder(
                new TransferRule(180).withTable(Map.of(
                        new TransferRule.TransferKey("B", "L1", "L2"), 60)));
        RouteGraph graph = graphOf(
                edge("A", "B", "L1", 100),
                edge("B", "C", "L2", 50));

        FoundPath path = measured.find(graph, "A", "C");

        assertEquals(100 + 50 + 60, path.totalSec());
        assertEquals(1, path.transferCount());
    }

    private static Edge edge(String from, String to, String routeId, int travelSec) {
        return new Edge(from, to, routeId, travelSec, 0);
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
