package com.ssafy.s15p21a104.domain.reroute;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.RouteCandidateFinder;
import com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder;
import com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorRouteSet;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * replan RAPTOR 이관 테스트(5부 D1, 티켓 `route-replan-raptor-migration`).
 *
 * <p>RAPTOR에만 있는 급행 노선(X1, B→C 40초)을 심어, replan이 레거시가 아니라
 * RAPTOR 경로로 후보를 내는지 판별한다(레거시 그래프에는 X1이 없다).
 */
class RerouteRaptorTest {

    private static RerouteService serviceWith() {
        var graph = graphOf(
                subway("A", "B", "L1", 100),
                subway("B", "C", "L1", 100),
                subway("B", "D", "L2", 50),
                subway("D", "C", "L2", 50));
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        for (String id : List.of("A", "B", "C", "D")) {
            infos.put(id, new RouteMapper.StationInfo(id, id + "역", 37.5, 127.0));
        }
        RaptorRouteSet routeSet = new RaptorRouteSet(List.of(
                new RaptorFinder.Route("L1", TravelMode.SUBWAY, List.of("A", "B", "C"),
                        new int[]{100, 100}, 0),
                new RaptorFinder.Route("L2", TravelMode.SUBWAY, List.of("B", "D", "C"),
                        new int[]{50, 50}, 0),
                new RaptorFinder.Route("X1", TravelMode.SUBWAY, List.of("B", "C"),
                        new int[]{40}, 0)), List.of());
        var finder = new RouteCandidateFinder(
                new TransferRule(180), Map.of(), Set.of(), infos, Map::of,
                BusRouteIndex.build(Map.of()),
                new RouteCandidateFinder.RaptorInput(routeSet, null));
        return new RerouteService(finder, () -> graph);
    }

    @Test
    @DisplayName("R-T1: replan이 RAPTOR를 탄다 — RAPTOR 전용 급행(X1, 40초)이 1등")
    void rt1_raptor사용() {
        List<RerouteResult> result = serviceWith().replan("B", "C", 0, 0);

        assertTrue(!result.isEmpty());
        assertEquals(40 / 60.0, result.get(0).route().totalMinutes(), 0.02);
    }

    @Test
    @DisplayName("R-T2: 잔여 계약 유지 — legs 합=총계, B에서 시작해 C에서 끝남, 후보 서명 전부 상이")
    void rt2_계약() {
        List<RerouteResult> result = serviceWith().replan("B", "C", 0, 0);

        assertTrue(result.size() >= 2);
        Set<String> signatures = new HashSet<>();
        for (RerouteResult r : result) {
            double sum = r.route().legs().stream().mapToDouble(RouteLegResponse::minutes).sum();
            assertEquals(r.route().totalMinutes(), sum, 0.01);
            assertEquals("B", r.route().legs().get(0).fromNodeId());
            assertEquals("C", r.route().legs().get(r.route().legs().size() - 1).toNodeId());
            StringBuilder signature = new StringBuilder();
            for (RouteLegResponse leg : r.route().legs()) {
                signature.append(leg.mode()).append(':')
                        .append(leg.fromNodeId()).append("->").append(leg.toNodeId()).append(':')
                        .append(leg.routeId()).append('|');
            }
            assertTrue(signatures.add(signature.toString()), "중복 후보: " + signature);
        }
    }
}
