package com.ssafy.s15p21a104.domain.route.service;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static org.junit.jupiter.api.Assertions.assertEquals;

import com.ssafy.s15p21a104.domain.route.RouteTestFixtures;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-190 합 일치 RED.
 * totalMinutes = leg minutes 합 (대기·환승 포함).
 */
class TotalMinutes190Test {

    @Test
    @DisplayName("190-T8: 환승 포함 경로도 합이 일치한다")
    void t8_환승포함_합일치() {
        List<RouteSearchResponse> result = RouteTestFixtures.serviceWith(graphOf(
                subway("A", "B", "L1", 100),
                subway("B", "C", "L2", 50)), Set.of())
                .search("A", "C", null, null, null);

        RouteSearchResponse first = result.get(0);
        double sum = first.legs().stream().mapToDouble(RouteLegResponse::minutes).sum();
        assertEquals(first.totalMinutes(), sum, 1e-9);
    }

    @Test
    @DisplayName("190-T9: 접근 포함 경로도 합이 일치한다 (TRANSFER 없음)")
    void t9_접근포함_합일치() {
        List<RouteSearchResponse> result = RouteTestFixtures.serviceWith(graphOf(
                subway("A", "C", "L1", 900),
                RouteTestFixtures.walk("A", "R1", 120),
                RouteTestFixtures.bike("R1", "R2", 120),
                RouteTestFixtures.walk("R2", "C", 120)), Set.of("R1", "R2"))
                .search("A", "C", null, null, null);

        RouteSearchResponse first = result.get(0);
        // 접근 leg는 WALK·BIKE 모드 그대로, TRANSFER 없음.
        assertEquals(0, first.transferCount());
        assertEquals(0, first.legs().stream()
                .filter(leg -> leg.mode() == TravelMode.TRANSFER).count());
        double sum = first.legs().stream().mapToDouble(RouteLegResponse::minutes).sum();
        assertEquals(first.totalMinutes(), sum, 1e-9);
    }

    @Test
    @DisplayName("190-T10: 대기 포함 경로도 합이 일치한다")
    void t10_대기포함_합일치() {
        com.ssafy.s15p21a104.domain.route.graph.RouteGraph graph = graphOf(
                new com.ssafy.s15p21a104.domain.route.graph.Edge(
                        "A", "B", "L1", 100, 60, TravelMode.SUBWAY),
                new com.ssafy.s15p21a104.domain.route.graph.Edge(
                        "B", "C", "L1", 100, 60, TravelMode.SUBWAY));
        List<RouteSearchResponse> result = RouteTestFixtures.serviceWith(graph, Set.of())
                .search("A", "C", null, null, null);

        RouteSearchResponse first = result.get(0);
        // 이동 200 + 첫 승차 대기 60 = 260초 = 4.333분.
        assertEquals((100 + 100 + 60) / 60.0, first.totalMinutes(), 1e-9);
        // leg 소요는 이동만, 탑승 대기는 waitMinutes로 분리 — 합(이동+대기)은 총계와 일치한다.
        RouteLegResponse leg = first.legs().get(0);
        assertEquals(200 / 60.0, leg.minutes(), 1e-9);
        assertEquals(60 / 60.0, leg.waitMinutes(), 1e-9);
        double sum = first.legs().stream()
                .mapToDouble(l -> l.minutes() + (l.waitMinutes() == null ? 0 : l.waitMinutes()))
                .sum();
        assertEquals(first.totalMinutes(), sum, 1e-9);
    }
}
