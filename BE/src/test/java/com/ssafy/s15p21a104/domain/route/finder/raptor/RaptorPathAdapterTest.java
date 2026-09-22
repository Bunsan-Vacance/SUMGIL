package com.ssafy.s15p21a104.domain.route.finder.raptor;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.FoundPath;
import com.ssafy.s15p21a104.domain.route.finder.RouteCandidateFinder;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * RAPTOR → FoundPath 어댑터 계약 테스트 — corridor 마스킹(C1)·환승 표 일치(C2)·승차 대기 위치.
 */
class RaptorPathAdapterTest {

    private static final TransferRule TRANSFER_180 = new TransferRule(180);

    private static RaptorFinder.Route route(String id, TravelMode mode, int waitSec, String... stopsSecs) {
        List<String> stops = new ArrayList<>();
        int[] travel = new int[(stopsSecs.length - 1) / 2];
        for (int i = 0; i < stopsSecs.length; i += 2) {
            stops.add(stopsSecs[i]);
            if (i + 1 < stopsSecs.length) {
                travel[i / 2] = Integer.parseInt(stopsSecs[i + 1]);
            }
        }
        return new RaptorFinder.Route(id, mode, stops, travel, waitSec);
    }

    private static BusRouteIndex busIndex(String[]... routes) {
        Map<String, List<BusEdgeBuilder.RouteStop>> map = new HashMap<>();
        float lat = 37.50f;
        for (String[] stops : routes) {
            List<BusEdgeBuilder.RouteStop> list = new ArrayList<>();
            for (int i = 0; i < stops.length; i++) {
                list.add(new BusEdgeBuilder.RouteStop(stops[i], i + 1, (double) lat, 127.0));
            }
            map.put(stops[0] + "-route", list);
        }
        return BusRouteIndex.build(map);
    }

    @Test
    @DisplayName("A1: 버스 두 노선 — BUS corridor 마스킹 + 환승 1회 + 총계(환승 상수 포함)")
    void a1_버스corridor마스킹() {
        List<RaptorFinder.Route> routes = List.of(
                route("r1", TravelMode.BUS, 0, "A", "100", "B", "100", "C"),
                route("r2", TravelMode.BUS, 0, "C", "100", "D", "100", "E"));
        BusRouteIndex index = busIndex(new String[]{"A", "B", "C"}, new String[]{"C", "D", "E"});
        RaptorFinder finder = new RaptorFinder(routes, List.of());
        RaptorFinder.Journey journey = finder
                .find("A", "E", Map.of("A", 0), Map.of("E", 0), 3, false).get(0);

        FoundPath path = RaptorPathAdapter
                .toFoundPath(journey, routes, TRANSFER_180, index).orElseThrow();

        assertTrue(path.edges().stream().allMatch(edge -> "BUS".equals(edge.routeId())),
                "BUS leg은 corridor routeId로 마스킹되어야 한다");
        assertEquals(1, path.transferCount());
        assertEquals(400 + 180, path.totalSec());
        assertEquals(path.stations().size() - 1, path.edges().size());
    }

    @Test
    @DisplayName("A2: 지하철 승차 대기 — 첫 엣지 waitSec, 총계 반영")
    void a2_지하철승차대기() {
        List<RaptorFinder.Route> routes = List.of(
                route("1002", TravelMode.SUBWAY, 30, "A", "120", "B"));
        RaptorFinder finder = new RaptorFinder(routes, List.of());
        RaptorFinder.Journey journey = finder
                .find("A", "B", Map.of("A", 0), Map.of("B", 0), 2, false).get(0);

        FoundPath path = RaptorPathAdapter
                .toFoundPath(journey, routes, TRANSFER_180, null).orElseThrow();

        assertEquals("1002", path.edges().get(0).routeId());
        assertEquals(30, path.edges().get(0).waitSec());
        assertEquals(150, path.totalSec()); // 120 + 대기 30
        assertEquals(0, path.transferCount());
    }

    @Test
    @DisplayName("A3: 좌표 접근 — 탑승 대기는 합산하지 않고 탑승 엣지 waitSec로 남긴다")
    void a3_좌표접근시대기_분리() {
        List<RaptorFinder.Route> routes = List.of(
                route("r1", TravelMode.BUS, 30, "A", "100", "B"));
        RaptorFinder finder = new RaptorFinder(routes, List.of());
        RaptorFinder.Journey journey = finder
                .find("PLACE-ORIGIN", "B", Map.of("A", 60), Map.of("B", 0), 2, false).get(0);

        FoundPath path = RaptorPathAdapter
                .toFoundPath(journey, routes, TRANSFER_180, null).orElseThrow();

        assertEquals(TravelMode.WALK, path.edges().get(0).mode());
        assertEquals(0, path.edges().get(0).waitSec());
        assertEquals(100, path.edges().get(1).travelSec()); // 이동만 — 대기 합산 금지
        assertEquals(30, path.edges().get(1).waitSec());   // 대기는 탑승 엣지에 분리
        assertEquals(60 + 100 + 30, path.totalSec());
    }

    @Test
    @DisplayName("A5: 두 번째 탑승 대기도 자기 탑승 엣지 waitSec로 남는다(합산 금지)")
    void a5_중간탑승대기_분리() {
        List<RaptorFinder.Route> routes = List.of(
                route("s1", TravelMode.SUBWAY, 30, "A", "100", "B"),
                route("s2", TravelMode.SUBWAY, 45, "B", "100", "D"));
        RaptorFinder finder = new RaptorFinder(routes, List.of());
        RaptorFinder.Journey journey = finder
                .find("A", "D", Map.of("A", 0), Map.of("D", 0), 3, false).get(0);

        FoundPath path = RaptorPathAdapter
                .toFoundPath(journey, routes, TRANSFER_180, null).orElseThrow();

        assertEquals(2, path.edges().size());
        assertEquals(100, path.edges().get(0).travelSec());
        assertEquals(30, path.edges().get(0).waitSec());
        assertEquals(100, path.edges().get(1).travelSec());
        assertEquals(45, path.edges().get(1).waitSec());
        // 이동 200 + 대기 75 + 환승 180(B 환승역)
        assertEquals(100 + 30 + 100 + 45 + 180, path.totalSec());
    }

    @Test
    @DisplayName("A4: 매퍼 통합 — TRANSFER leg 생성·legs 합 = totalMinutes (계약 검증)")
    void a4_매퍼통합() {
        List<RaptorFinder.Route> routes = List.of(
                route("r1", TravelMode.BUS, 0, "A", "100", "B", "100", "C"),
                route("r2", TravelMode.BUS, 0, "C", "100", "D", "100", "E"));
        BusRouteIndex index = busIndex(new String[]{"A", "B", "C"}, new String[]{"C", "D", "E"});
        RaptorFinder finder = new RaptorFinder(routes, List.of());
        RaptorFinder.Journey journey = finder
                .find("A", "E", Map.of("A", 0), Map.of("E", 0), 3, false).get(0);
        FoundPath path = RaptorPathAdapter
                .toFoundPath(journey, routes, TRANSFER_180, index).orElseThrow();

        List<Long> transferSecs = RouteCandidateFinder.transferSeconds(
                path.edges(), TRANSFER_180, index);
        List<RouteMapper.EngineSegment> segments = new ArrayList<>();
        for (Edge edge : path.edges()) {
            segments.add(new RouteMapper.EngineSegment(edge.fromNode(), edge.toNode(),
                    edge.routeId(), edge.travelSec(), edge.mode(), edge.waitSec()));
        }
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        for (String id : List.of("A", "B", "C", "D", "E")) {
            infos.put(id, new RouteMapper.StationInfo(id, id + "역", 37.5, 127.0));
        }
        Optional<RouteSearchResponse> response = RouteMapper.toResponseWithTransfers(
                new RouteMapper.EnginePath(segments, path.totalSec(), path.transferCount()),
                infos, RouteType.SHORTEST, RouteSource.ALGORITHM, transferSecs,
                index);

        assertTrue(response.isPresent(), "매퍼가 어댑터 산출 FoundPath를 거부했다");
        RouteSearchResponse route = response.get();
        double legsSum = route.legs().stream()
                .mapToDouble(leg -> leg.minutes() + (leg.waitMinutes() == null ? 0 : leg.waitMinutes()))
                .sum();
        assertEquals(route.totalMinutes(), legsSum, 0.02);
        assertEquals(path.transferCount(), route.transferCount());
        assertEquals(1, route.legs().stream()
                .filter(leg -> leg.mode() == TravelMode.TRANSFER).count());
    }
}
