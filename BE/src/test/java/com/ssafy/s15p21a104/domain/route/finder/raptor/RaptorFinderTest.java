package com.ssafy.s15p21a104.domain.route.finder.raptor;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bus;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.FoundPath;
import com.ssafy.s15p21a104.domain.route.finder.KShortestPathFinder;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * RAPTOR 프로토타입 단위 테스트 — 도달·중간 하차·환승·연결·대기·calm·기존 엔진 대조.
 */
class RaptorFinderTest {

    private static RaptorFinder.Route route(String routeId, int waitSec, String... stopsSecs) {
        // stopsSecs = [stop, sec, stop, sec, stop, ...]
        List<String> stops = new java.util.ArrayList<>();
        int[] travel = new int[(stopsSecs.length - 1) / 2];
        for (int i = 0; i < stopsSecs.length; i += 2) {
            stops.add(stopsSecs[i]);
            if (i + 1 < stopsSecs.length) {
                travel[i / 2] = Integer.parseInt(stopsSecs[i + 1]);
            }
        }
        return new RaptorFinder.Route(routeId, TravelMode.BUS, stops, travel, waitSec);
    }

    private static Map<String, Integer> access(String stop, int sec) {
        return Map.of(stop, sec);
    }

    @Test
    @DisplayName("R1: 단일 노선 — 중간 하차 정류장까지 한 leg")
    void r1_중간하차() {
        RaptorFinder finder = new RaptorFinder(List.of(
                route("B1", 0, "A", "100", "B", "100", "C", "100", "D")), List.of());

        List<RaptorFinder.Journey> journeys =
                finder.find("A", "C", access("A", 0), access("C", 0), 3, false);

        assertEquals(1, journeys.size());
        RaptorFinder.Journey journey = journeys.get(0);
        assertEquals(200, journey.totalSec());
        assertEquals(0, journey.transfers());
        // 접근 + 탑승 A→C + 도착 접근 = 3 legs
        assertEquals(3, journey.legs().size());
        assertEquals("B1", journey.legs().get(1).routeId());
        assertEquals("A", journey.legs().get(1).from());
        assertEquals("C", journey.legs().get(1).to());
    }

    @Test
    @DisplayName("R2: 환승 1회 — 라운드 2에서 다른 노선으로 갈아탄다")
    void r2_환승() {
        RaptorFinder finder = new RaptorFinder(List.of(
                route("B1", 0, "A", "100", "B", "100", "C"),
                route("B2", 0, "C", "100", "D", "100", "E")), List.of());

        List<RaptorFinder.Journey> journeys =
                finder.find("A", "E", access("A", 0), access("E", 0), 3, false);

        assertTrue(!journeys.isEmpty());
        RaptorFinder.Journey best = journeys.get(journeys.size() - 1);
        assertEquals(400, best.totalSec());
        assertEquals(1, best.transfers());
        assertEquals("B1", best.legs().get(1).routeId());
        assertEquals("B2", best.legs().get(2).routeId());
    }

    @Test
    @DisplayName("R3: 도보 연결 — 노선 밖 60초 연결로 환승한다")
    void r3_도보연결() {
        RaptorFinder finder = new RaptorFinder(List.of(
                route("B1", 0, "A", "100", "B"),
                route("B2", 0, "C", "100", "D")),
                List.of(new RaptorFinder.Connection("B", "C", 60, TravelMode.WALK)));

        List<RaptorFinder.Journey> journeys =
                finder.find("A", "D", access("A", 0), access("D", 0), 3, false);

        assertTrue(!journeys.isEmpty());
        RaptorFinder.Journey best = journeys.get(journeys.size() - 1);
        assertEquals(260, best.totalSec());
        assertTrue(best.legs().stream().anyMatch(leg -> leg.mode() == TravelMode.WALK
                && "B".equals(leg.from()) && "C".equals(leg.to())));
    }

    @Test
    @DisplayName("R4: 승차 대기 — 노선 waitSec이 탑승마다 더해진다")
    void r4_대기() {
        RaptorFinder finder = new RaptorFinder(List.of(
                route("B1", 30, "A", "100", "B", "100", "C")), List.of());

        List<RaptorFinder.Journey> journeys =
                finder.find("A", "C", access("A", 0), access("C", 0), 3, false);

        assertEquals(230, journeys.get(0).totalSec());
    }

    @Test
    @DisplayName("R5: calm — 혼잡 비용이면 느린 우회 노선이 선택된다")
    void r5_혼잡우회() {
        RaptorFinder.Route direct = route("R1", 0, "A", "400", "D");
        RaptorFinder.Route detour = route("R2", 0, "A", "250", "B", "250", "D");
        RaptorFinder.SegmentCost congested = (routeId, fromIdx, toIdx, passThroughSec, travelSec) ->
                "R1".equals(routeId) ? travelSec * 2L : travelSec;
        RaptorFinder finder = new RaptorFinder(List.of(direct, detour), List.of(), congested);

        List<RaptorFinder.Journey> fast =
                finder.find("A", "D", access("A", 0), access("D", 0), 3, false);
        List<RaptorFinder.Journey> calm =
                finder.find("A", "D", access("A", 0), access("D", 0), 3, true);

        assertEquals("R1", fast.get(0).legs().get(1).routeId());
        assertEquals(400, fast.get(0).totalSec());
        // R1은 시간 400이지만 혼잡 비용 800, R2는 시간 500·비용 500 — calm은 R2를 고른다.
        assertEquals("R2", calm.get(0).legs().get(1).routeId());
        assertEquals(500, calm.get(0).totalSec());
        assertEquals(500, calm.get(0).totalCost());
    }

    @Test
    @DisplayName("R6: 접근·이탈 시간이 총계에 포함된다")
    void r6_접근이탈() {
        RaptorFinder finder = new RaptorFinder(List.of(
                route("B1", 0, "A", "100", "B")), List.of());

        List<RaptorFinder.Journey> journeys =
                finder.find("ORIGIN", "DEST", access("A", 60), access("B", 30), 3, false);

        assertEquals(190, journeys.get(0).totalSec()); // 60 + 100 + 30
    }

    @Test
    @DisplayName("R7: 기존 엔진과 대조 — 같은 최단 총계")
    void r7_기존엔진대조() {
        // 같은 데이터를 그래프(엣지)와 노선(시퀀스)으로 각각 조립한다. 환승 상수 0으로 맞춘다.
        var graph = graphOf(
                bus("A", "B", "B1", 100), bus("B", "C", "B1", 100),
                bus("C", "D", "B2", 100), bus("D", "E", "B2", 100));
        List<FoundPath> enginePaths = new KShortestPathFinder(new TransferRule(0))
                .findK(graph, "A", "E", 1);

        RaptorFinder finder = new RaptorFinder(List.of(
                route("B1", 0, "A", "100", "B", "100", "C"),
                route("B2", 0, "C", "100", "D", "100", "E")), List.of());
        List<RaptorFinder.Journey> journeys =
                finder.find("A", "E", access("A", 0), access("E", 0), 3, false);

        assertEquals(enginePaths.get(0).totalSec(),
                journeys.get(journeys.size() - 1).totalSec());
    }

    @Test
    @DisplayName("R8: 좌표 접근 — 출발지(PLACE) 연결로 첫 정류장에 닿는다")
    void r8_좌표접근() {
        // PLACE-ORIGIN → A 도보 60s, 노선 A→B 100s, B → PLACE-DEST 도보 30s.
        RaptorFinder finder = new RaptorFinder(List.of(
                route("B1", 0, "A", "100", "B")),
                List.of(
                        new RaptorFinder.Connection("PLACE-ORIGIN", "A", 60, TravelMode.WALK),
                        new RaptorFinder.Connection("B", "PLACE-DEST", 30, TravelMode.WALK)));

        List<RaptorFinder.Journey> journeys = finder.find("PLACE-ORIGIN", "PLACE-DEST",
                access("PLACE-ORIGIN", 0), access("PLACE-DEST", 0), 3, false);

        assertTrue(!journeys.isEmpty(), "좌표 접근 경로가 없다 (접근 연결 이완 누락)");
        RaptorFinder.Journey journey = journeys.get(0);
        assertEquals(190, journey.totalSec()); // 60 + 100 + 30
        RaptorFinder.Leg walkToA = journey.legs().stream()
                .filter(leg -> leg.from().equals("PLACE-ORIGIN") && leg.to().equals("A"))
                .findFirst().orElseThrow();
        assertEquals(TravelMode.WALK, walkToA.mode());
    }
}
