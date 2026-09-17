package com.ssafy.s15p21a104.domain.route;

import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder.Stop;
import com.ssafy.s15p21a104.domain.route.bike.BikeRentalEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.loader.RouteEdgeRow;
import com.ssafy.s15p21a104.domain.route.loader.RouteGraphLoader;
import com.ssafy.s15p21a104.domain.route.loader.RouteGraphRawData;
import com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-137 그래프 조립 계약 검증. 실제 빌더를 합쳐 만든 그래프에서
 * "같은 유형=주행 수단, 다른 유형=도보" 규칙이 지켜지는지 본다. DB·Redis 없이 green.
 *
 * <p>정류장 접점(M3·M6~M8)과 BUS(M9)는 S15P21A104-121 인접이라 이 파일에서 다루지 않는다.
 */
class GraphAssemblyContractTest {

    // 역 S1·S2 (약 176m), 대여소 R1·R2 (약 176m). S1-R1 79m, S2-R2 79m, S1-R2 255m, S2-R1 97m.
    private static final Map<String, Stop> STATIONS = Map.of(
            "S1", new Stop("S1", 37.5000, 127.0000),
            "S2", new Stop("S2", 37.5000, 127.0020));
    private static final Map<String, Stop> RENTALS = Map.of(
            "R1", new Stop("R1", 37.5000, 127.0009),
            "R2", new Stop("R2", 37.5000, 127.0029));

    private RouteGraph assemble() {
        List<Edge> extra = new ArrayList<>();
        extra.addAll(WalkEdgeBuilder.build(STATIONS, RENTALS));
        extra.addAll(BikeRentalEdgeBuilder.build(RENTALS));
        return RouteGraphLoader.load(
                new RouteGraphRawData(
                        List.of(new RouteEdgeRow("S1", "S2", "L1", 300, 0)),
                        Map.of("S1", "1역", "S2", "2역"), Map.of("L1", "1호선")),
                extra).graph();
    }

    @Test
    @DisplayName("t_역대역_간선은_SUBWAY만")
    void t_역대역_간선은_SUBWAY만() {
        RouteGraph g = assemble();

        assertTrue(g.outgoingEdges("S1").stream()
                .filter(e -> e.toNode().equals("S2"))
                .allMatch(e -> e.mode() == TravelMode.SUBWAY));
        assertTrue(g.outgoingEdges("S1").stream()
                .noneMatch(e -> e.toNode().equals("S2")
                        && (e.mode() == TravelMode.BIKE || e.mode() == TravelMode.WALK)));
    }

    @Test
    @DisplayName("t_역대여소_간선은_WALK만")
    void t_역대여소_간선은_WALK만() {
        RouteGraph g = assemble();

        assertTrue(g.outgoingEdges("S1").stream()
                .filter(e -> e.toNode().equals("R1"))
                .count() > 0);
        assertTrue(g.outgoingEdges("S1").stream()
                .filter(e -> e.toNode().equals("R1"))
                .allMatch(e -> e.mode() == TravelMode.WALK));
        assertTrue(g.outgoingEdges("S1").stream()
                .noneMatch(e -> e.toNode().equals("R1") && e.mode() == TravelMode.BIKE));
    }

    @Test
    @DisplayName("t_대여소역_간선은_WALK만")
    void t_대여소역_간선은_WALK만() {
        RouteGraph g = assemble();

        assertTrue(g.outgoingEdges("R1").stream()
                .filter(e -> e.toNode().equals("S1"))
                .allMatch(e -> e.mode() == TravelMode.WALK));
        assertTrue(g.outgoingEdges("R1").stream()
                .noneMatch(e -> e.toNode().equals("S1") && e.mode() == TravelMode.BIKE));
    }

    @Test
    @DisplayName("t_대여소대여소_간선은_BIKE만")
    void t_대여소대여소_간선은_BIKE만() {
        RouteGraph g = assemble();

        assertTrue(g.outgoingEdges("R1").stream()
                .filter(e -> e.toNode().equals("R2"))
                .count() > 0);
        assertTrue(g.outgoingEdges("R1").stream()
                .filter(e -> e.toNode().equals("R2"))
                .allMatch(e -> e.mode() == TravelMode.BIKE));
        assertTrue(g.outgoingEdges("R1").stream()
                .noneMatch(e -> e.toNode().equals("R2") && e.mode() == TravelMode.WALK));
    }

    @Test
    @DisplayName("t_대여소노드도_그래프정점에_등록된다")
    void t_대여소노드도_그래프정점에_등록된다() {
        RouteGraph g = assemble();

        assertTrue(g.containsNode("R1"));
        assertTrue(g.nodes().containsAll(Set.of("S1", "S2", "R1", "R2")));
    }
}
