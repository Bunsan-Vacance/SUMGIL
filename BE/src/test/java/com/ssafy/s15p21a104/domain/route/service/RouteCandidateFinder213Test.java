package com.ssafy.s15p21a104.domain.route.service;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.RouteTestFixtures;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.RouteCandidateFinder;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-213 T4 탐색 파이프라인 분리 RED.
 * 탐색→매핑 조립을 RouteCandidateFinder가 맡고 서비스는 조립만 한다.
 */
class RouteCandidateFinder213Test {

    @Test
    @DisplayName("213-T4: 탐색 1회로 시간순 후보가 나온다 (routeType 미지정)")
    void t4_탐색조립_시간순() {
        RouteGraph graph = graphOf(
                subway("A", "B", "L1", 100),
                subway("B", "C", "L1", 100),
                subway("A", "D", "L2", 150),
                subway("D", "C", "L2", 150));
        RouteCandidateFinder finder = new RouteCandidateFinder(
                new TransferRule(180), Map.of(), Set.of(),
                RouteTestFixtures.stationInfos("A", "B", "C", "D"));

        List<RouteSearchResponse> result = finder.findCandidates(graph, "A", "C", 10);

        assertTrue(result.size() >= 2);
        for (int i = 1; i < result.size(); i++) {
            assertTrue(result.get(i - 1).totalMinutes() <= result.get(i).totalMinutes());
        }
    }

    @Test
    @DisplayName("213-T4: 라벨러가 첫 후보를 SHORTEST로 매긴다")
    void t4_라벨러_SHORTEST() {
        List<RouteSearchResponse> ranked = RouteCandidateFinder.relabelByRank(List.of(
                RouteTestFixtures.serviceWith(graphOf(subway("A", "C", "L1", 300)), Set.of())
                        .search("A", "C", null, null, null).get(0)));

        assertEquals(1, ranked.size());
        assertEquals(RouteType.SHORTEST, ranked.get(0).routeType());
    }

    @Test
    @DisplayName("213-T4: modes 필터가 허용 수단만 남긴다")
    void t4_모드필터() {
        List<RouteSearchResponse> candidates = RouteTestFixtures.serviceWith(graphOf(
                subway("A", "C", "L1", 300),
                RouteTestFixtures.bike("A", "R1", 400),
                RouteTestFixtures.bike("R1", "C", 400)), Set.of())
                .search("A", "C", null, null, null);

        List<RouteSearchResponse> filtered =
                RouteCandidateFinder.filterByModes(candidates, List.of(TravelMode.BIKE));

        assertTrue(filtered.size() >= 1);
        assertTrue(filtered.stream().flatMap(c -> c.legs().stream())
                .allMatch(leg -> leg.mode() == TravelMode.BIKE
                        || leg.mode() == TravelMode.WALK
                        || leg.mode() == TravelMode.TRANSFER));
    }
}
