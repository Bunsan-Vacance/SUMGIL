package com.ssafy.s15p21a104.domain.route.finder.raptor;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteStopsReader;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.loader.RouteEdgeRow;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * RAPTOR 노선 조립기 테스트 — 지하철 방향·순서·보류 링크·순환선, 버스 실 CSV, 연결.
 */
class RaptorRouteSetBuilderTest {

    private static RouteEdgeRow row(String from, String to, String line, int sec, int wait) {
        return new RouteEdgeRow(from, to, line, sec, wait);
    }

    @Test
    @DisplayName("S1: 지하철 양방향 — 역번호 규칙으로 두 방향 체인, 승차 대기는 구간값")
    void s1_양방향체인() {
        List<RaptorFinder.Route> routes = RaptorRouteSetBuilder.subwayRoutes(List.of(
                row("201", "202", "1002", 120, 30),
                row("202", "203", "1002", 120, 30),
                row("203", "202", "1002", 120, 20),
                row("202", "201", "1002", 120, 20)));

        assertEquals(2, routes.size());
        RaptorFinder.Route up = routes.stream()
                .filter(route -> route.stops().get(0).equals("201")).findFirst().orElseThrow();
        assertEquals(List.of("201", "202", "203"), up.stops());
        assertEquals(120, up.travelSec()[0]);
        assertEquals(30, up.boardWaitSec()[0]);
        assertEquals(30, up.boardWaitSec()[1]);
        assertEquals(0, up.boardWaitSec()[2]);
        RaptorFinder.Route down = routes.stream()
                .filter(route -> route.stops().get(0).equals("203")).findFirst().orElseThrow();
        assertEquals(List.of("203", "202", "201"), down.stops());
    }

    @Test
    @DisplayName("S2: 규칙 보류 링크(반전 3개)는 체인 끝/시작에 붙는다")
    void s2_보류링크부착() {
        // 250→156 은 SubwayDirectionResolver 가 보류하는 링크(2호선 성수지선).
        List<RaptorFinder.Route> routes = RaptorRouteSetBuilder.subwayRoutes(List.of(
                row("250", "156", "1002", 90, 10),
                row("156", "157", "1002", 90, 10)));

        assertEquals(1, routes.size());
        assertEquals(List.of("250", "156", "157"), routes.get(0).stops());
    }

    @Test
    @DisplayName("S3: 순환선은 사이클을 두 바퀴로 펼친다")
    void s3_순환선() {
        List<RaptorFinder.Route> routes = RaptorRouteSetBuilder.subwayRoutes(List.of(
                row("201", "202", "1002", 60, 0),
                row("202", "203", "1002", 60, 0),
                row("203", "201", "1002", 60, 0),
                row("202", "201", "1002", 60, 0),
                row("203", "202", "1002", 60, 0),
                row("201", "203", "1002", 60, 0)));

        assertEquals(2, routes.size());
        for (RaptorFinder.Route route : routes) {
            assertEquals(7, route.stops().size()); // 3정류장×2바퀴+시작 반복
            assertEquals(6, route.travelSec().length);
        }
    }

    @Test
    @DisplayName("S4: 버스 실 CSV — 노선 수·구간 산식 확인")
    void s4_버스실CSV() {
        List<RaptorFinder.Route> routes = RaptorRouteSetBuilder.busRoutes(BusRouteStopsReader.read());

        assertTrue(routes.size() >= 700, "버스 노선이 너무 적다: " + routes.size());
        for (RaptorFinder.Route route : routes) {
            assertEquals(route.stops().size() - 1, route.travelSec().length);
            assertEquals(route.stops().size(), route.boardWaitSec().length);
            assertEquals(TravelMode.BUS, route.mode());
            assertTrue(route.travelSec().length >= 1);
        }
    }

    @Test
    @DisplayName("S5: 연결 — 도보(역↔대여소)·자전거(대여소↔대여소)")
    void s5_연결() {
        Map<String, BikeEdgeBuilder.Stop> stations =
                Map.of("S1", new BikeEdgeBuilder.Stop("S1", 37.5, 127.0));
        Map<String, BikeEdgeBuilder.Stop> rentals = Map.of(
                "R1", new BikeEdgeBuilder.Stop("R1", 37.5, 127.0045),
                "R2", new BikeEdgeBuilder.Stop("R2", 37.5, 127.0090));

        List<RaptorFinder.Connection> connections =
                RaptorRouteSetBuilder.connections(stations, rentals, Map.of());

        assertTrue(connections.stream().anyMatch(c -> c.mode() == TravelMode.WALK
                && c.from().equals("S1") && c.to().equals("R1")));
        assertTrue(connections.stream().anyMatch(c -> c.mode() == TravelMode.BIKE
                && c.from().equals("R1") && c.to().equals("R2")));
    }
}
