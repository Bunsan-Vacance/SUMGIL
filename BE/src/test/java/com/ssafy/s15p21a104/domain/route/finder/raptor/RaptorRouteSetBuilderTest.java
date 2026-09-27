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
    @DisplayName("S6: 지선이 섞여도 본선 체인이 빠지지 않는다 — 행 순서 무관·결정적")
    void s6_분기_본선누락방지() {
        List<RouteEdgeRow> main = List.of(
                row("201", "202", "1002", 60, 0),
                row("202", "203", "1002", 60, 0),
                row("203", "204", "1002", 60, 0),
                row("202", "201", "1002", 60, 0),
                row("203", "202", "1002", 60, 0),
                row("204", "203", "1002", 60, 0));
        List<RouteEdgeRow> branch = List.of(
                row("250", "251", "1002", 60, 0),
                row("251", "250", "1002", 60, 0));

        // 지선 행이 먼저 오는 순서 — 예전 구현은 시작점으로 지선을 골라 본선을 버릴 수 있었다.
        List<RouteEdgeRow> branchFirst = new java.util.ArrayList<>(branch);
        branchFirst.addAll(main);
        List<RouteEdgeRow> mainFirst = new java.util.ArrayList<>(main);
        mainFirst.addAll(branch);

        List<String> branchFirstRoutes = routeStops(RaptorRouteSetBuilder.subwayRoutes(branchFirst));
        List<String> mainFirstRoutes = routeStops(RaptorRouteSetBuilder.subwayRoutes(mainFirst));

        assertEquals(mainFirstRoutes, branchFirstRoutes, "행 순서에 따라 노선 조립이 달라졌다");
        assertTrue(branchFirstRoutes.stream().anyMatch(route -> route.contains("201>202>203>204")),
                "본선 체인이 빠졌다: " + branchFirstRoutes);
        assertTrue(branchFirstRoutes.stream().anyMatch(route -> route.contains("250>251")),
                "지선 체인이 빠졌다: " + branchFirstRoutes);
    }

    @Test
    @DisplayName("S7: 역번호가 오르내리는 노선(수인분당 형태)도 한 방향이 노선 하나로 조립된다 (267)")
    void s7_역번호역전_수인분당() {
        // 선릉 220 · 한티 1024 · 도곡 334 · 구룡 1026 · 개포동 1027 · 대모산입구 1028 · 수서 339 · 복정 2821
        List<String> order = List.of("220", "1024", "334", "1026", "1027", "1028", "339", "2821");

        List<String> routes = routeStops(RaptorRouteSetBuilder.subwayRoutes(bidirectional(order, "1075")));

        assertTrue(routes.contains("1075:" + String.join(">", order)), "하행 체인이 조각났다: " + routes);
        assertTrue(routes.contains("1075:" + String.join(">", order.reversed())), "상행 체인이 조각났다: " + routes);
    }

    @Test
    @DisplayName("S8: 중간 역번호 역전(8호선 가락시장·남위례 형태)도 노선 하나로 조립된다 (267)")
    void s8_역번호역전_8호선() {
        // 송파 2817 · 가락시장 340 · 문정 2819 · 장지 2820 · 복정 2821 · 남위례 2828 · 산성 2822 · 남한산성입구 2823
        List<String> order = List.of("2817", "340", "2819", "2820", "2821", "2828", "2822", "2823");

        List<RaptorFinder.Route> built = RaptorRouteSetBuilder.subwayRoutes(bidirectional(order, "1008"));
        List<String> routes = routeStops(built);

        assertTrue(routes.contains("1008:" + String.join(">", order)), "하행 체인이 조각났다: " + routes);
        assertTrue(routes.contains("1008:" + String.join(">", order.reversed())), "상행 체인이 조각났다: " + routes);
        RaptorFinder.Route down = built.stream()
                .filter(route -> route.stops().equals(order)).findFirst().orElseThrow();
        for (int i = 0; i < order.size() - 1; i++) {
            assertEquals(60 + i, down.travelSec()[i], "구간 소요가 어긋났다: " + i);
            assertEquals(10 + i, down.boardWaitSec()[i], "승차 대기가 어긋났다: " + i);
        }
    }

    /** 정차 순서대로 양방향 구간 행 — 하행 i번 구간 소요 60+i초·대기 10+i초, 상행은 90초·20초. */
    private static List<RouteEdgeRow> bidirectional(List<String> order, String line) {
        List<RouteEdgeRow> rows = new java.util.ArrayList<>();
        for (int i = 0; i + 1 < order.size(); i++) {
            rows.add(row(order.get(i), order.get(i + 1), line, 60 + i, 10 + i));
            rows.add(row(order.get(i + 1), order.get(i), line, 90, 20));
        }
        return rows;
    }

    /** 노선 집합을 순서 무관 비교용 문자열로 — routeId + 정차 순서. */
    private static List<String> routeStops(List<RaptorFinder.Route> routes) {
        return routes.stream()
                .map(route -> route.routeId() + ":" + String.join(">", route.stops()))
                .sorted()
                .toList();
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
