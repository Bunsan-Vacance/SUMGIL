package com.ssafy.s15p21a104.domain.route.finder;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bike;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.walk;
import static org.junit.jupiter.api.Assertions.assertEquals;

import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-232 WALK 경유 노선유지 환승 집계 RED.
 * WALK를 지나도 직전 대중교통 노선을 유지해 다음 대중교통과 비교한다.
 */
class TransferKeepLine232Test {

    private final ShortestPathFinder finder = new ShortestPathFinder(new TransferRule(180));

    @Test
    @DisplayName("232-T1: SUBWAY→WALK→다른 SUBWAY는 환승 1회 + 비용 가산")
    void t1_도보경유_환승1회() {
        RouteGraph graph = graphOf(
                subway("A", "B", "L1", 100),
                walk("B", "C", 60),
                subway("C", "D", "L2", 50));

        FoundPath path = finder.find(graph, "A", "D");

        assertEquals(1, path.transferCount());
        assertEquals(100 + 60 + 50 + 180, path.totalSec());
    }

    @Test
    @DisplayName("232-T2: SUBWAY→WALK→같은 SUBWAY는 환승 아님")
    void t2_도보경유_같은노선_환승아님() {
        RouteGraph graph = graphOf(
                subway("A", "B", "L1", 100),
                walk("B", "C", 60),
                subway("C", "D", "L1", 50));

        FoundPath path = finder.find(graph, "A", "D");

        assertEquals(0, path.transferCount());
        assertEquals(100 + 60 + 50, path.totalSec());
    }

    @Test
    @DisplayName("232-T3: 첫 탑승 전 접근 도보는 환승 아님 (213-T1 유지)")
    void t3_첫탑승_환승아님() {
        RouteGraph graph = graphOf(
                walk("A", "B", 60),
                bike("B", "C", 120),
                walk("C", "D", 60));

        FoundPath path = finder.find(graph, "A", "D");

        assertEquals(0, path.transferCount());
        assertEquals(60 + 120 + 60, path.totalSec());
    }
}
