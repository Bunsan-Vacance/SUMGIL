package com.ssafy.s15p21a104.domain.route.finder;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-190 슬롯·대기시간 RED.
 * 첫 승차 대기(waitSec) 1회 부과 + 환승 시 중복 계상 없음.
 */
class DepartureWait190Test {

    private static Edge subwayWait(String from, String to, String routeId, int travelSec, int waitSec) {
        return new Edge(from, to, routeId, travelSec, waitSec, TravelMode.SUBWAY);
    }

    @Test
    @DisplayName("190-T1: 첫 승차 대기가 총 소요에 1회 들어간다")
    void t1_첫승차대기_1회() {
        RouteGraph graph = graphOf(
                subwayWait("A", "B", "L1", 100, 60),
                subwayWait("B", "C", "L1", 100, 60));

        FoundPath path = new ShortestPathFinder(new TransferRule(180)).find(graph, "A", "C");

        // 이동 200 + 첫 승차 대기 60. 두 번째 엣지 대기는 부과 안 함 (중복 방지).
        assertEquals(List.of("A", "B", "C"), path.stations());
        assertEquals(100 + 100 + 60, path.totalSec());
        assertEquals(0, path.transferCount());
    }

    @Test
    @DisplayName("190-T2: 환승 시 대기 중복 계상 없다 (환승 상수만)")
    void t2_환승_대기중복없음() {
        RouteGraph graph = graphOf(
                subwayWait("A", "B", "L1", 100, 60),
                subwayWait("B", "C", "L2", 50, 90));

        FoundPath path = new ShortestPathFinder(new TransferRule(180)).find(graph, "A", "C");

        // 이동 150 + 첫 승차 대기 60 + 환승 180. B역 대기 90은 부과 안 함.
        assertEquals(100 + 50 + 60 + 180, path.totalSec());
        assertEquals(1, path.transferCount());
    }

    @Test
    @DisplayName("190-T3: waitSec 없으면(0) 대기 가산 없다")
    void t3_대기없음_가산없음() {
        RouteGraph graph = graphOf(
                new Edge("A", "B", "L1", 100, 0, TravelMode.SUBWAY),
                new Edge("B", "C", "L1", 100, 0, TravelMode.SUBWAY));

        FoundPath path = new ShortestPathFinder(new TransferRule(180)).find(graph, "A", "C");

        assertEquals(200, path.totalSec());
    }

    @Test
    @DisplayName("190-T4: 대기 분리 — 비용에 부과된 첫 탑승 엣지만 waitSec를 남긴다")
    void t4_대기_엣지_위치() {
        RouteGraph graph = graphOf(
                subwayWait("A", "B", "L1", 100, 60),
                subwayWait("B", "C", "L1", 100, 60));

        FoundPath path = new ShortestPathFinder(new TransferRule(180)).find(graph, "A", "C");

        assertEquals(60, path.edges().get(0).waitSec());
        assertEquals(0, path.edges().get(1).waitSec());
    }
}
