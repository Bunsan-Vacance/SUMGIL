package com.ssafy.s15p21a104.domain.route.mapper;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteOptionResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.TransitionType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.Arrays;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-237 구간 전환·대여소 식별 RED (FE-BE 통합 계약 §3).
 */
class LegContract237Test {

    private static RouteLegResponse leg(TravelMode mode, String from, String to, String routeId) {
        return leg(mode, from, to, routeId, null);
    }

    private static RouteLegResponse leg(TravelMode mode, String from, String to, String routeId,
            List<RouteOptionResponse> routeOptions) {
        return new RouteLegResponse(mode,
                from, from + "역", 37.5, 127.0, to, to + "역", 37.5, 127.01,
                routeId, 5.0, null, "unavailable", null, null, routeOptions);
    }

    private static List<RouteOptionResponse> busOptions(String... routeIds) {
        return Arrays.stream(routeIds)
                .map(routeId -> new RouteOptionResponse(routeId, null, null))
                .toList();
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

    @Test
    @DisplayName("사용자 환승 횟수는 실제 탑승 경계만 센다")
    void 사용자_환승_횟수_실제탑승경계() {
        List<RouteLegResponse> legs = List.of(
                leg(TravelMode.WALK, "O", "R", "WALK"),
                leg(TravelMode.BIKE, "R", "R2", "BIKE"),
                leg(TravelMode.WALK, "R2", "A", "WALK"),
                leg(TravelMode.SUBWAY, "A", "B", "1003"),
                leg(TravelMode.TRANSFER, "B", "B", null),
                leg(TravelMode.SUBWAY, "B", "C", "1075"),
                leg(TravelMode.TRANSFER, "C", "C", null),
                leg(TravelMode.SUBWAY, "C", "D", "1008"),
                leg(TravelMode.WALK, "D", "X", "WALK"));

        assertEquals(3, LegContract.userTransferCount(
                LegContract.withContractFields(legs, Set.of())));
    }

    @Test
    @DisplayName("도보를 사이에 둔 자전거·대중교통 경계는 각각 센다")
    void 도보_사이_자전거_경계() {
        assertEquals(1, LegContract.userTransferCount(List.of(
                leg(TravelMode.SUBWAY, "A", "B", "L1"),
                leg(TravelMode.WALK, "B", "R", "WALK"),
                leg(TravelMode.BIKE, "R", "S", "BIKE"))));
        assertEquals(2, LegContract.userTransferCount(List.of(
                leg(TravelMode.SUBWAY, "A", "B", "L1"),
                leg(TravelMode.WALK, "B", "R", "WALK"),
                leg(TravelMode.BIKE, "R", "S", "BIKE"),
                leg(TravelMode.WALK, "S", "C", "WALK"),
                leg(TravelMode.SUBWAY, "C", "D", "L1"))));
        assertEquals(2, LegContract.userTransferCount(List.of(
                leg(TravelMode.SUBWAY, "A", "B", "L1"),
                leg(TravelMode.WALK, "B", "R", "WALK"),
                leg(TravelMode.BIKE, "R", "S", "BIKE"),
                leg(TravelMode.WALK, "S", "C", "WALK"),
                leg(TravelMode.SUBWAY, "C", "D", "L2"))));
    }

    @Test
    @DisplayName("같은 노선 분할·단일 자전거·첫 탑승은 환승이 아니다")
    void 같은노선_분할은_환승아님() {
        assertEquals(0, LegContract.userTransferCount(List.of(
                leg(TravelMode.BIKE, "A", "B", "BIKE"),
                leg(TravelMode.BIKE, "B", "C", "BIKE"))));
        assertEquals(0, LegContract.userTransferCount(List.of(
                leg(TravelMode.SUBWAY, "A", "B", "L1"),
                leg(TravelMode.SUBWAY, "B", "C", "L1"))));
        assertEquals(2, LegContract.userTransferCount(List.of(
                leg(TravelMode.SUBWAY, "A", "B", "L1"),
                leg(TravelMode.SUBWAY, "B", "C", "L2"),
                leg(TravelMode.SUBWAY, "C", "D", "L3"))));
        assertEquals(0, LegContract.userTransferCount(List.of(
                leg(TravelMode.BIKE, "A", "B", "BIKE"))));
    }

    @Test
    @DisplayName("BUS는 구간별 공통 routeOptions를 누적해 판정한다")
    void 버스_공통노선_교집합() {
        assertEquals(1, LegContract.userTransferCount(List.of(
                leg(TravelMode.BUS, "A", "B", "BUS", busOptions("108", "143")),
                leg(TravelMode.BUS, "B", "C", "BUS", busOptions("143", "205")),
                leg(TravelMode.BUS, "C", "D", "BUS", busOptions("205", "999")))));
    }

    @Test
    @DisplayName("노선 정보가 없으면 명시 TRANSFER만 보조하고 앞뒤 행위는 세지 않는다")
    void 노선정보_없음과_명시TRANSFER() {
        List<RouteLegResponse> unknownTransfer = List.of(
                leg(TravelMode.SUBWAY, "A", "B", "L1"),
                leg(TravelMode.TRANSFER, "B", "B", null),
                leg(TravelMode.SUBWAY, "B", "C", null));
        assertEquals(1, LegContract.userTransferCount(
                LegContract.withContractFields(unknownTransfer, Set.of())));
        assertEquals(1, LegContract.userTransferCount(
                LegContract.withContractFields(List.of(
                        leg(TravelMode.SUBWAY, "A", "B", "L1"),
                        leg(TravelMode.TRANSFER, "B", "B", null),
                        leg(TravelMode.SUBWAY, "B", "C", "L1")), Set.of())));
        assertEquals(0, LegContract.userTransferCount(List.of(
                leg(TravelMode.SUBWAY, "A", "B", null),
                leg(TravelMode.SUBWAY, "B", "C", null))));
        assertEquals(0, LegContract.userTransferCount(
                LegContract.withContractFields(List.of(
                        leg(TravelMode.TRANSFER, "A", "A", null),
                        leg(TravelMode.SUBWAY, "A", "B", "L1"),
                        leg(TravelMode.TRANSFER, "B", "B", null)), Set.of())));
    }
}
