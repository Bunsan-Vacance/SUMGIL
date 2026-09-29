package com.ssafy.s15p21a104.domain.route.finder;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/** 수단 교체 상한(S15P21A104-337) — 탑승 = 같은 노선 연속 구간 1회, 자전거 런 1회. */
class ModeChangePolicyTest {

    private static Edge e(TravelMode mode, String routeId) {
        return new Edge("A", "B", routeId, 60, 0, mode);
    }

    @Test
    @DisplayName("337-T1: 같은 노선 연속 구간은 1회 탑승, 도보·환승은 세지 않는다")
    void t1_탑승세기() {
        List<Edge> edges = List.of(
                e(TravelMode.WALK, "WALK"),
                e(TravelMode.SUBWAY, "L2"), e(TravelMode.SUBWAY, "L2"),   // 2호선 1회
                e(TravelMode.TRANSFER, "TRANSFER"),
                e(TravelMode.SUBWAY, "L8"),                               // 8호선 1회
                e(TravelMode.WALK, "WALK"),
                e(TravelMode.BIKE, "BIKE"), e(TravelMode.BIKE, "BIKE"));  // 자전거 런 1회

        assertEquals(2, ModeChangePolicy.modeChanges(edges)); // 탑승 3회 → 교체 2회
    }

    @Test
    @DisplayName("337-T2: 수단 교체 3회까지 허용, 4회는 거부 — 버스→버스→지하철→자전거(3회)는 통과")
    void t2_상한() {
        List<Edge> three = List.of(
                e(TravelMode.BUS, "740"), e(TravelMode.WALK, "WALK"), e(TravelMode.BUS, "서초10"),
                e(TravelMode.SUBWAY, "L3"), e(TravelMode.BIKE, "BIKE"));
        List<Edge> four = List.of(
                e(TravelMode.BIKE, "BIKE"), e(TravelMode.BUS, "740"), e(TravelMode.BUS, "서초10"),
                e(TravelMode.SUBWAY, "L3"), e(TravelMode.BIKE, "BIKE"));

        assertTrue(ModeChangePolicy.allowedPath(three));
        assertFalse(ModeChangePolicy.allowedPath(four));
    }
}
