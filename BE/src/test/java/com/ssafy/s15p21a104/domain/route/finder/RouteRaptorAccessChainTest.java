package com.ssafy.s15p21a104.domain.route.finder;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bus;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder;
import com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorRouteSet;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 접근·이탈 closure 경계 통합 테스트(5부 R-A2) — 연결망 다중 홉(대여소 체인)이
 * {@link RouteCandidateFinder}를 지나 RAPTOR 여정(BIKE leg 포함)으로 이어지는지 확인한다.
 *
 * <p>엔진 단독으로는 1홉만 이완되므로(설계 계약), 체인은 경계에서 테이블로 공급된다.
 */
class RouteRaptorAccessChainTest {

    private static final List<String> NODES =
            List.of("PLACE-ORIGIN", "PLACE-DEST", "R1", "R2", "S", "D", "A");

    private static RouteCandidateFinder finder(RaptorRouteSet routeSet, List<Edge> accessEdges) {
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        for (String id : NODES) {
            infos.put(id, new RouteMapper.StationInfo(id, id, 37.5, 127.0));
        }
        return new RouteCandidateFinder(new TransferRule(0), Map.of(), Set.of(), infos, Map::of,
                BusRouteIndex.build(Map.of()),
                new RouteCandidateFinder.RaptorInput(routeSet, accessEdges));
    }

    @Test
    @DisplayName("C1: 출발 접근 자전거 체인 2홉이 노선 탑승으로 이어진다")
    void c1_출발체인() {
        RaptorRouteSet routeSet = new RaptorRouteSet(List.of(
                new RaptorFinder.Route("B1", TravelMode.BUS, List.of("S", "D"),
                        new int[]{100}, 0)),
                List.of(
                        new RaptorFinder.Connection("R1", "R2", 120, TravelMode.BIKE),
                        new RaptorFinder.Connection("R2", "S", 120, TravelMode.BIKE),
                        new RaptorFinder.Connection("D", "PLACE-DEST", 30, TravelMode.WALK)));
        List<Edge> access = List.of(new Edge(
                "PLACE-ORIGIN", "R1", "WALK", 60, 0, TravelMode.WALK));
        RouteCandidateFinder finder = finder(routeSet, access);

        List<ScoredCandidate> candidates = finder.findCandidatesWithPaths(
                graphOf(bus("S", "D", "B1", 100)), "PLACE-ORIGIN", "PLACE-DEST", 3, null, null);

        assertTrue(!candidates.isEmpty(), "연결망 다중 홉 후보가 없다 (접근 closure 누락)");
        RouteSearchResponse best = candidates.get(0).response();
        assertEquals(430 / 60.0, best.totalMinutes(), 0.02); // 60 + 120 + 120 + 100 + 30
        // 연속 BIKE 연결은 대여~반납 1 leg로 합쳐진다(로드맵 1단계 계약).
        double bikeMinutes = best.legs().stream()
                .filter(leg -> leg.mode() == TravelMode.BIKE)
                .mapToDouble(leg -> leg.minutes())
                .sum();
        assertEquals(240 / 60.0, bikeMinutes, 0.02);
    }

    @Test
    @DisplayName("C2: 도착 이탈 자전거 체인이 연결된다")
    void c2_도착체인() {
        RaptorRouteSet routeSet = new RaptorRouteSet(List.of(
                new RaptorFinder.Route("B2", TravelMode.BUS, List.of("A", "S"),
                        new int[]{100}, 0)),
                List.of(
                        new RaptorFinder.Connection("S", "R2", 120, TravelMode.BIKE),
                        new RaptorFinder.Connection("R2", "R1", 120, TravelMode.BIKE),
                        new RaptorFinder.Connection("R1", "PLACE-DEST", 60, TravelMode.WALK)));
        List<Edge> access = List.of(new Edge(
                "PLACE-ORIGIN", "A", "WALK", 30, 0, TravelMode.WALK));
        RouteCandidateFinder finder = finder(routeSet, access);

        List<ScoredCandidate> candidates = finder.findCandidatesWithPaths(
                graphOf(bus("A", "S", "B2", 100)), "PLACE-ORIGIN", "PLACE-DEST", 3, null, null);

        assertTrue(!candidates.isEmpty(), "연결망 다중 홉 후보가 없다 (이탈 closure 누락)");
        RouteSearchResponse best = candidates.get(0).response();
        assertEquals(430 / 60.0, best.totalMinutes(), 0.02); // 30 + 100 + 120 + 120 + 60
        double bikeMinutes = best.legs().stream()
                .filter(leg -> leg.mode() == TravelMode.BIKE)
                .mapToDouble(leg -> leg.minutes())
                .sum();
        assertEquals(240 / 60.0, bikeMinutes, 0.02);
    }
}
