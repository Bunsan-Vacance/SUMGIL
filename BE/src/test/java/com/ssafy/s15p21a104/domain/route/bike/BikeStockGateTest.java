package com.ssafy.s15p21a104.domain.route.bike;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-110 재고 폴백 게이트 검증. DB 없이 green.
 */
class BikeStockGateTest {

    private static RouteLegResponse bikeLeg(String from) {
        return new RouteLegResponse(TravelMode.BIKE,
                from, "출발", 37.5, 127.0, "C", "도착", 37.5, 127.0,
                BikeEdgeBuilder.BIKE_ROUTE_ID, 4.0, null, "unavailable");
    }

    private static RouteLegResponse subwayLeg() {
        return new RouteLegResponse(TravelMode.SUBWAY,
                "A", "출발", 37.5, 127.0, "C", "도착", 37.5, 127.0,
                "L1", 15.0, null, "unavailable");
    }

    @Test
    @DisplayName("110-T1: 재고 있으면 후보 유지")
    void t110_재고있음_유지() {
        assertTrue(BikeStockGate.passes(
                List.of(bikeLeg("R1")), Map.of("R1", 5)));
    }

    @Test
    @DisplayName("110-T2: 재고 0이면 후보 제외")
    void t110_재고없음_제외() {
        assertFalse(BikeStockGate.passes(
                List.of(subwayLeg(), bikeLeg("R1")), Map.of("R1", 0)));
    }

    @Test
    @DisplayName("110-T3: 원천 없으면 기본 허용")
    void t110_원천없음_허용() {
        assertTrue(BikeStockGate.passes(
                List.of(bikeLeg("R1")), Map.of()));
        assertTrue(BikeStockGate.passes(
                List.of(subwayLeg()), Map.of("R1", 0)));
    }
}
