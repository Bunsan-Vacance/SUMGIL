package com.ssafy.s15p21a104.domain.route.mapper;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.TransitionType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-237 구간 전환·대여소 식별 RED (FE-BE 통합 계약 §3).
 */
class LegContract237Test {

    private static RouteLegResponse leg(TravelMode mode, String from, String to, String routeId) {
        return new RouteLegResponse(mode,
                from, from + "역", 37.5, 127.0, to, to + "역", 37.5, 127.01,
                routeId, 5.0, null, "unavailable", null, null, null);
    }

    @Test
    @DisplayName("237-L1: 대중교통 사이 TRANSFER 구간은 TRANSFER다")
    void l1_환승은TRANSFER() {
        List<RouteLegResponse> legs = List.of(
                leg(TravelMode.SUBWAY, "A", "B", "L1"),
                leg(TravelMode.TRANSFER, "B", "B", null),
                leg(TravelMode.SUBWAY, "B", "C", "L2"));

        List<RouteLegResponse> result = LegContract.withContractFields(legs, Set.of());

        assertEquals(TransitionType.TRANSFER, result.get(1).transitionType());
        assertNull(result.get(0).transitionType());
        assertNull(result.get(0).fromRentalId());
    }

    @Test
    @DisplayName("237-L2: 첫 대중교통 앞 TRANSFER는 BOARDING, 마지막 뒤는 ALIGHTING이다")
    void l2_승하차구분() {
        List<RouteLegResponse> legs = List.of(
                leg(TravelMode.WALK, "H", "A", "WALK"),
                leg(TravelMode.TRANSFER, "A", "A", null),
                leg(TravelMode.SUBWAY, "A", "B", "L1"),
                leg(TravelMode.TRANSFER, "B", "B", null),
                leg(TravelMode.WALK, "B", "O", "WALK"));

        List<RouteLegResponse> result = LegContract.withContractFields(legs, Set.of());

        assertEquals(TransitionType.BOARDING, result.get(1).transitionType());
        assertEquals(TransitionType.ALIGHTING, result.get(3).transitionType());
    }

    @Test
    @DisplayName("237-L3: 대여소 ID는 BIKE 구간에 명시하고 유형은 TRANSFER 구간에만 둔다")
    void l3_대여는RENTAL() {
        List<RouteLegResponse> legs = List.of(
                leg(TravelMode.WALK, "H", "R1", "WALK"),
                leg(TravelMode.BIKE, "R1", "R2", "R1"),
                leg(TravelMode.WALK, "R2", "O", "WALK"));

        List<RouteLegResponse> result =
                LegContract.withContractFields(legs, Set.of("R1", "R2"));

        // FE 검증이 transitionType을 TRANSFER 모드에서만 허용한다 — BIKE 구간은 null.
        assertNull(result.get(1).transitionType());
        assertEquals("R1", result.get(1).fromRentalId());
        assertEquals("R2", result.get(1).toRentalId());
    }

    @Test
    @DisplayName("237-L4: 대여소 도착 BIKE도 유형은 null, ID만 명시한다")
    void l4_반납은RETURN() {
        List<RouteLegResponse> legs = List.of(
                leg(TravelMode.BIKE, "X", "R2", "R9"));

        List<RouteLegResponse> result =
                LegContract.withContractFields(legs, Set.of("R2"));

        assertNull(result.get(0).transitionType());
        assertNull(result.get(0).fromRentalId());
        assertEquals("R2", result.get(0).toRentalId());
    }
}
