package com.ssafy.s15p21a104.domain.route.finder;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bus;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static org.junit.jupiter.api.Assertions.assertEquals;

import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder;
import com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorRouteSet;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * fast 프리셋 불변 테스트(5부 C2, 티켓 `route-heuristic-cost-layer`).
 *
 * <p>fast = 실제 총 소요시간 최소(취향·혼잡 페널티 없음). 혼잡 비용 모델을 주면 순위가
 * 바뀌는 케이스에서, 주지 않은 fast 탐색은 시간최단을 그대로 유지해야 한다.
 */
class RouteRaptorFastInvarianceTest {

    private static Map<String, RouteMapper.StationInfo> infos() {
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        for (String id : List.of("A", "B", "D")) {
            infos.put(id, new RouteMapper.StationInfo(id, id, 37.5, 127.0));
        }
        return infos;
    }

    private static BusRouteIndex index() {
        return BusRouteIndex.build(Map.of(
                "R1", List.of(
                        new BusEdgeBuilder.RouteStop("A", 1, 37.50, 127.0),
                        new BusEdgeBuilder.RouteStop("D", 2, 37.50, 127.03)),
                "R2", List.of(
                        new BusEdgeBuilder.RouteStop("A", 1, 37.50, 127.0),
                        new BusEdgeBuilder.RouteStop("B", 2, 37.50, 127.01),
                        new BusEdgeBuilder.RouteStop("D", 3, 37.50, 127.03))));
    }

    private static RaptorRouteSet routeSet() {
        return new RaptorRouteSet(List.of(
                new RaptorFinder.Route("R1", TravelMode.BUS, List.of("A", "D"),
                        new int[]{400}, 0),
                new RaptorFinder.Route("R2", TravelMode.BUS, List.of("A", "B", "D"),
                        new int[]{250, 250}, 0)), List.of());
    }

    private static RouteCandidateFinder finder() {
        return new RouteCandidateFinder(new TransferRule(0), Map.of(), Set.of(), infos(), Map::of,
                index(), new RouteCandidateFinder.RaptorInput(routeSet(), null));
    }

    @Test
    @DisplayName("C2: fast는 혼잡 비용 모델을 받지 않는다 — 페널티가 순위를 바꾸는 케이스에서도 시간최단 유지")
    void c2_fast불변() {
        var graph = graphOf(
                bus("A", "B", "R2", 250), bus("B", "D", "R2", 250),
                bus("A", "D", "R1", 400));
        // R1(400s 직행)을 3배로 벌하는 비용 모델 — calm이면 우회 R2(500s)가 이긴다.
        KShortestPathFinder.EdgeCostModel penalty =
                edge -> "R1".equals(edge.routeId()) ? edge.travelSec() * 3 : edge.travelSec();

        List<ScoredCandidate> fast = finder().findCandidatesWithPaths(
                graph, "A", "D", 5, null, null);
        List<ScoredCandidate> calm = finder().findCandidatesWithPaths(
                graph, "A", "D", 5, null, penalty);

        assertEquals(400 / 60.0, fast.get(0).response().totalMinutes(), 0.02,
                "fast가 혼잡 페널티를 반영했다");
        assertEquals(500 / 60.0, calm.get(0).response().totalMinutes(), 0.02,
                "calm이 혼잡 페널티를 반영하지 않았다");
    }
}
