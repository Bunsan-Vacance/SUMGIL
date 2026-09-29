package com.ssafy.s15p21a104.domain.reroute;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.RouteTestFixtures;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry;
import com.ssafy.s15p21a104.domain.route.geometry.RailGeometryRegistry;
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
 * S15P21A104-193 잔여 경로 재탐색 RED.
 * 현 위치 이후 잔여 구간을 탐색하고 전체/잔여 시간을 구분한다.
 */
class RerouteService193Test {

    private RerouteService serviceWith() {
        var graph = graphOf(
                subway("A", "B", "L1", 100),
                subway("B", "C", "L1", 100),
                subway("B", "D", "L2", 50),
                subway("D", "C", "L2", 50));
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        for (String id : List.of("A", "B", "C", "D")) {
            infos.put(id, new RouteMapper.StationInfo(id, id + "역", 37.5, 127.0));
        }
        var finder = new com.ssafy.s15p21a104.domain.route.finder.RouteCandidateFinder(
                new TransferRule(180), Map.of(), Set.of(), infos, Map::of);
        return new RerouteService(finder, () -> graph);
    }

    @Test
    @DisplayName("193-T1: 현 위치부터 목적지까지 잔여 후보를 반환한다")
    void t1_잔여후보() {
        RerouteService service = serviceWith();

        // B에서 C까지. B→C 직통(100) vs B→D→C(100+환승180). 직통이 잔여 최단.
        List<RerouteResult> result = service.replan("B", "C", 0, 0);

        assertTrue(result.size() >= 1);
        RerouteResult first = result.get(0);
        assertTrue(first.reason() != null && !first.reason().isEmpty());
        assertEquals("ALGORITHM", first.source());
        // 잔여 legs는 B에서 시작해 C에서 끝난다.
        RouteSearchResponse route = first.route();
        assertEquals("B", route.legs().get(0).fromNodeId());
        assertEquals("C", route.legs().get(route.legs().size() - 1).toNodeId());
        // 잔여 totalMinutes = 잔여 legs 합 (±0.01).
        double sum = route.legs().stream()
                .mapToDouble(com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse::minutes)
                .sum();
        assertEquals(route.totalMinutes(), sum, 0.01);
    }

    @Test
    @DisplayName("193-T2: 잔여 연결 불가면 빈 목록이다 (에러 아님)")
    void t2_잔여없음_빈목록() {
        RerouteService service = serviceWith();

        List<RerouteResult> result = service.replan("C", "A", 0, 0);

        assertTrue(result.isEmpty());
    }

    @Test
    @DisplayName("193-T3: 전체/잔여 시간 혼동 없음 — 잔여가 전체보다 짧다")
    void t3_잔여가전체보다짧다() {
        RerouteService service = serviceWith();

        // A→B→C 전체(200) vs B→C 잔여(100). 잔여가 짧아야 한다.
        List<RerouteResult> full = service.replan("A", "C", 0, 0);
        List<RerouteResult> remain = service.replan("B", "C", 0, 0);

        assertTrue(full.size() >= 1 && remain.size() >= 1);
        assertTrue(remain.get(0).route().totalMinutes() < full.get(0).route().totalMinutes());
    }

    @Test
    @DisplayName("193-T4: 잔여 후보들의 leg 서명은 서로 다르다 (중복 탐색 버그 회귀)")
    void t4_후보leg서명_서로다르다() {
        RerouteService service = serviceWith();

        // B→C: 직통 L1 vs B→D→C L2 — 서로 다른 leg 서명이어야 한다.
        List<RerouteResult> result = service.replan("B", "C", 0, 0);

        assertTrue(result.size() >= 2);
        Set<String> signatures = new HashSet<>();
        for (RerouteResult r : result) {
            StringBuilder signature = new StringBuilder();
            for (var leg : r.route().legs()) {
                signature.append(leg.mode()).append(':')
                        .append(leg.fromNodeId()).append("->").append(leg.toNodeId()).append(':')
                        .append(leg.routeId()).append('|');
            }
            assertTrue(signatures.add(signature.toString()), "중복 후보: " + signature);
        }
    }

    @Test
    @DisplayName("replan-geometry: 잔여 후보에 표시용 후처리(노선 이름·geometry)를 적용한다 — 검색과 같은 단계")
    void 표시후처리_적용() {
        RerouteService plain = serviceWith();
        java.util.List<java.util.List<RouteSearchResponse>> seen = new java.util.ArrayList<>();
        RerouteService decorated = plain.withDisplay(routes -> {
            seen.add(routes);
            return routes.stream().map(r -> new RouteSearchResponse(
                    r.routeType(), r.totalMinutes(), r.legs(), r.source(),
                    12345.0, r.transferCount(), r.congestionPrediction())).toList();
        });

        List<RerouteResult> result = decorated.replan("B", "C", 0, 0);

        assertEquals(1, seen.size(), "후처리는 잔여 후보 묶음에 한 번");
        assertTrue(result.size() >= 1);
        assertTrue(result.stream().allMatch(r -> Double.valueOf(12345.0).equals(r.route().totalDistanceMeters())),
                "후처리 결과가 응답에 반영돼야 한다");
    }
}
