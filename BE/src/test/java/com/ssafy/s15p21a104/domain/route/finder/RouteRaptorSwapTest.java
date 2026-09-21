package com.ssafy.s15p21a104.domain.route.finder;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bus;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder;
import com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorRouteSet;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 엔진 교체 동등성 테스트(S15P21A104-217 ③) — 같은 입력에 레거시(K 라벨링)와 RAPTOR가
 * 같은 계약 형태(거리·환승·BUS corridor 표현)를 내는지 확인한다. 값은 알고리즘이 달라도 되지만
 * 이 합성 케이스에서는 최단이 유일해 총계까지 같아야 한다.
 */
class RouteRaptorSwapTest {

    private static Map<String, RouteMapper.StationInfo> infos() {
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        for (String id : List.of("A", "B", "C", "D", "E")) {
            infos.put(id, new RouteMapper.StationInfo(id, id + "역", 37.5, 127.0));
        }
        return infos;
    }

    private static Map<String, List<BusEdgeBuilder.RouteStop>> routesMap() {
        return Map.of(
                "r1", List.of(
                        new BusEdgeBuilder.RouteStop("A", 1, 37.50, 127.0),
                        new BusEdgeBuilder.RouteStop("B", 2, 37.50, 127.01),
                        new BusEdgeBuilder.RouteStop("C", 3, 37.50, 127.02)),
                "r2", List.of(
                        new BusEdgeBuilder.RouteStop("C", 1, 37.50, 127.02),
                        new BusEdgeBuilder.RouteStop("D", 2, 37.50, 127.03),
                        new BusEdgeBuilder.RouteStop("E", 3, 37.50, 127.04)));
    }

    private static BusRouteIndex index() {
        return BusRouteIndex.build(routesMap());
    }

    /** 레거시 엔진용 corridor 그래프 — routeId "BUS"·고정 소요(RAPTOR 노선 집합과 같은 값). */
    private static com.ssafy.s15p21a104.domain.route.graph.RouteGraph corridorGraph() {
        return graphOf(
                new com.ssafy.s15p21a104.domain.route.graph.Edge(
                        "A", "B", "BUS", 100, 0, TravelMode.BUS),
                new com.ssafy.s15p21a104.domain.route.graph.Edge(
                        "B", "C", "BUS", 100, 0, TravelMode.BUS),
                new com.ssafy.s15p21a104.domain.route.graph.Edge(
                        "C", "D", "BUS", 100, 0, TravelMode.BUS),
                new com.ssafy.s15p21a104.domain.route.graph.Edge(
                        "D", "E", "BUS", 100, 0, TravelMode.BUS));
    }

    private static RaptorRouteSet routeSet() {
        return new RaptorRouteSet(List.of(
                new RaptorFinder.Route("r1", TravelMode.BUS, List.of("A", "B", "C"),
                        new int[]{100, 100}, 0),
                new RaptorFinder.Route("r2", TravelMode.BUS, List.of("C", "D", "E"),
                        new int[]{100, 100}, 0)), List.of());
    }

    @Test
    @DisplayName("S1: 같은 합성 그래프에서 두 엔진이 같은 총계·환승·BUS 계약을 낸다")
    void s1_엔진동등성() {
        var graph = corridorGraph();
        BusRouteIndex index = index();
        Map<String, RouteMapper.StationInfo> infos = infos();

        RouteCandidateFinder legacy = new RouteCandidateFinder(
                new TransferRule(180), Map.of(), Set.of(), infos, Map::of, index);
        RouteCandidateFinder raptor = new RouteCandidateFinder(
                new TransferRule(180), Map.of(), Set.of(), infos, Map::of, index,
                new RouteCandidateFinder.RaptorInput(routeSet(), null));

        List<ScoredCandidate> legacyCandidates =
                legacy.findCandidatesWithPaths(graph, "A", "E", 10, null, null);
        List<ScoredCandidate> raptorCandidates =
                raptor.findCandidatesWithPaths(graph, "A", "E", 10, null, null);

        assertTrue(!legacyCandidates.isEmpty(), "레거시 후보 없음");
        assertTrue(!raptorCandidates.isEmpty(), "RAPTOR 후보 없음");
        RouteSearchResponse legacyFirst = legacyCandidates.get(0).response();
        RouteSearchResponse raptorFirst = raptorCandidates.get(0).response();

        assertEquals(legacyFirst.totalMinutes(), raptorFirst.totalMinutes(), 0.01);
        assertEquals(legacyFirst.transferCount(), raptorFirst.transferCount());
        // BUS leg은 corridor 표현(routeId "BUS") + routeOptions — FE 계약(234) 유지(C1).
        for (RouteSearchResponse candidate : List.of(legacyFirst, raptorFirst)) {
            var busLegs = candidate.legs().stream()
                    .filter(leg -> leg.mode() == TravelMode.BUS).toList();
            assertTrue(!busLegs.isEmpty());
            assertTrue(busLegs.stream().allMatch(leg -> "BUS".equals(leg.routeId())),
                    "BUS routeId는 corridor여야 한다");
            assertTrue(busLegs.stream().allMatch(leg -> leg.routeOptions() != null
                    && !leg.routeOptions().isEmpty()), "routeOptions가 있어야 한다");
        }
    }

    @Test
    @DisplayName("S2: RAPTOR 입력이 비어 경로가 없으면 레거시가 결과를 낸다 (폴백)")
    void s2_폴백() {
        var graph = graphOf(
                bus("A", "B", "r1", 100), bus("B", "C", "r1", 100),
                bus("C", "D", "r2", 100), bus("D", "E", "r2", 100));
        // 정류장 A~E를 모르는 빈 노선 집합 → RAPTOR 결과 없음 → 레거시 폴백.
        RouteCandidateFinder finder = new RouteCandidateFinder(
                new TransferRule(180), Map.of(), Set.of(), infos(), Map::of, index(),
                new RouteCandidateFinder.RaptorInput(new RaptorRouteSet(List.of(), List.of()), null));

        List<ScoredCandidate> candidates =
                finder.findCandidatesWithPaths(graph, "A", "E", 10, null, null);

        assertTrue(!candidates.isEmpty(), "폴백이 결과를 내야 한다");
    }

    @Test
    @DisplayName("S3: modes 필터 — BUS 제외 요청은 RAPTOR가 버스 노선을 스캔하지 않는다")
    void s3_모드필터() {
        var graph = graphOf(
                bus("A", "B", "r1", 100), bus("B", "C", "r1", 100));
        RouteCandidateFinder finder = new RouteCandidateFinder(
                new TransferRule(180), Map.of(), Set.of(), infos(), Map::of, index(),
                new RouteCandidateFinder.RaptorInput(new RaptorRouteSet(
                        List.of(new RaptorFinder.Route("r1", TravelMode.BUS, List.of("A", "B", "C"),
                                new int[]{100, 100}, 0)), List.of()), null));

        List<ScoredCandidate> candidates = finder.findCandidatesWithPaths(
                graph, "A", "C", 10, List.of(TravelMode.SUBWAY), null);
        // RAPTOR·레거시 모두 BUS-only 경로는 제외한다 → 빈 후보(에러 아님).
        assertEquals(0, candidates.size());
    }

    @Test
    @DisplayName("S4: K 후보 — 금지 재스캔으로 서로 다른 후보를 채운다")
    void s4_K후보() {
        // 직통 버스(A→C 240s) vs 버스+지하철(A→B→C 200s) — leg 구성이 달라야 별도 후보가 된다.
        Map<String, List<BusEdgeBuilder.RouteStop>> routesMap = Map.of(
                "r1", List.of(
                        new BusEdgeBuilder.RouteStop("A", 1, 37.50, 127.0),
                        new BusEdgeBuilder.RouteStop("C", 2, 37.50, 127.02)),
                "r2", List.of(
                        new BusEdgeBuilder.RouteStop("A", 1, 37.50, 127.0),
                        new BusEdgeBuilder.RouteStop("B", 2, 37.50, 127.01)));
        BusRouteIndex index = BusRouteIndex.build(routesMap);
        var graph = graphOf(
                new com.ssafy.s15p21a104.domain.route.graph.Edge("A", "C", "BUS", 240, 0, TravelMode.BUS),
                new com.ssafy.s15p21a104.domain.route.graph.Edge("A", "B", "BUS", 100, 0, TravelMode.BUS),
                new com.ssafy.s15p21a104.domain.route.graph.Edge("B", "C", "1002", 100, 0, TravelMode.SUBWAY));
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        for (String id : List.of("A", "B", "C")) {
            infos.put(id, new RouteMapper.StationInfo(id, id + "역", 37.5, 127.0));
        }
        RaptorRouteSet set = new RaptorRouteSet(List.of(
                new RaptorFinder.Route("r1", TravelMode.BUS, List.of("A", "C"),
                        new int[]{240}, 0),
                new RaptorFinder.Route("r2", TravelMode.BUS, List.of("A", "B"),
                        new int[]{100}, 0),
                new RaptorFinder.Route("1002", TravelMode.SUBWAY, List.of("B", "C"),
                        new int[]{100}, 0)), List.of());
        RouteCandidateFinder finder = new RouteCandidateFinder(
                new TransferRule(180), Map.of(), Set.of(), infos, Map::of, index,
                new RouteCandidateFinder.RaptorInput(set, null));

        List<ScoredCandidate> candidates =
                finder.findCandidatesWithPaths(graph, "A", "C", 10, null, null);

        assertTrue(candidates.size() >= 2, "K 후보가 2건 미만: " + candidates.size());
        double first = candidates.get(0).response().totalMinutes();
        double second = candidates.get(1).response().totalMinutes();
        assertTrue(Math.abs(first - second) > 0.1, "후보 총계가 같다 (다양성 실패)");
    }
}
