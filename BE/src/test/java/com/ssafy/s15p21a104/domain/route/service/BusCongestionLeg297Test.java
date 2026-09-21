package com.ssafy.s15p21a104.domain.route.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.buscongestion.BusArrival;
import com.ssafy.s15p21a104.domain.buscongestion.BusCongestionGrade;
import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder.RouteStop;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * BUS 구간에 실시간 혼잡 등급을 붙이는 배선 (S15P21A104-297).
 *
 * <p>FE 계약은 {@code legs[].congestionGrade} 문자열 하나다(TO_FE-bus-congestion-01). 구간 단위이며
 * 후보 노선별 값이 아니다 — 그 정류소에 <b>가장 먼저 오는</b> 버스 기준이다.
 */
class BusCongestionLeg297Test {

    private static Map<String, List<RouteStop>> busRoutes() {
        return Map.of(
                "108", List.of(
                        new RouteStop("S1", 1, 37.5000, 127.0000),
                        new RouteStop("S2", 2, 37.5000, 127.0050)),
                "143", List.of(
                        new RouteStop("S1", 1, 37.5000, 127.0000),
                        new RouteStop("S2", 2, 37.5000, 127.0050)));
    }

    private static RouteLegResponse corridorBusLeg() {
        return new RouteLegResponse(TravelMode.BUS,
                "S1", "정류장1", 37.5, 127.0, "S2", "정류장2", 37.5, 127.01,
                BusEdgeBuilder.BUS_CORRIDOR_ROUTE_ID, 4.0, null, "unavailable", null, null, null);
    }

    private static RouteLegResponse plainBusLeg(String routeId) {
        return new RouteLegResponse(TravelMode.BUS,
                "S1", "정류장1", 37.5, 127.0, "S2", "정류장2", 37.5, 127.01,
                routeId, 4.0, null, "unavailable", null, null, null);
    }

    private static RouteLegResponse subwayLeg() {
        return new RouteLegResponse(TravelMode.SUBWAY,
                "S1", "역1", 37.5, 127.0, "150", "역2", 37.5, 127.01,
                "1001", 4.0, null, "unavailable", null, null, null);
    }

    private static RouteSearchResponse responseOf(RouteLegResponse... legs) {
        return new RouteSearchResponse(RouteType.SHORTEST, 4.0, List.of(legs),
                RouteSource.ALGORITHM, null, 0, null);
    }

    private static RouteNameResolver resolver(Function<String, Map<String, BusArrival>> congestion) {
        return new RouteNameResolver(
                ids -> Map.of(),
                ids -> Map.of("108", "108번", "143", "143번"),
                BusRouteIndex.build(busRoutes()),
                ids -> Map.of("108", 10),
                congestion);
    }

    private static Map<String, BusArrival> arrivals(BusArrival... rows) {
        Map<String, BusArrival> out = new java.util.LinkedHashMap<>();
        for (BusArrival row : rows) {
            out.put(row.routeId(), row);
        }
        return out;
    }

    @Test
    @DisplayName("297-L1: 정규 BUS 구간에 혼잡 등급이 붙는다")
    void l1_등급_부착() {
        RouteNameResolver resolver = resolver(stopId -> "S1".equals(stopId)
                ? arrivals(new BusArrival("108", BusCongestionGrade.NORMAL, 120))
                : Map.of());

        List<RouteSearchResponse> out = resolver.withRouteNames(List.of(responseOf(corridorBusLeg())));

        assertEquals("NORMAL", out.get(0).legs().get(0).congestionGrade());
    }

    @Test
    @DisplayName("297-L2: 후보가 여럿이면 먼저 오는 버스의 등급을 쓴다")
    void l2_먼저_오는_버스() {
        RouteNameResolver resolver = resolver(stopId -> arrivals(
                new BusArrival("108", BusCongestionGrade.SATURATED, 600),
                new BusArrival("143", BusCongestionGrade.RELAXED, 90)));

        List<RouteSearchResponse> out = resolver.withRouteNames(List.of(responseOf(corridorBusLeg())));

        assertEquals("RELAXED", out.get(0).legs().get(0).congestionGrade(),
                "143 이 90초 뒤라 그 등급이 구간 대푯값이다");
    }

    @Test
    @DisplayName("297-L3: 후보 밖 노선의 값은 쓰지 않는다")
    void l3_후보_밖_노선() {
        RouteNameResolver resolver = resolver(stopId -> arrivals(
                new BusArrival("999", BusCongestionGrade.SATURATED, 10),
                new BusArrival("108", BusCongestionGrade.NORMAL, 300)));

        List<RouteSearchResponse> out = resolver.withRouteNames(List.of(responseOf(corridorBusLeg())));

        assertEquals("NORMAL", out.get(0).legs().get(0).congestionGrade(),
                "999 는 이 구간 후보가 아니다");
    }

    @Test
    @DisplayName("297-L4: 값이 없으면 null — 지어내지 않는다")
    void l4_값_없음() {
        RouteNameResolver resolver = resolver(stopId -> Map.of());

        List<RouteSearchResponse> out = resolver.withRouteNames(List.of(responseOf(corridorBusLeg())));

        assertNull(out.get(0).legs().get(0).congestionGrade());
    }

    @Test
    @DisplayName("297-L5: 지하철 구간엔 붙이지 않는다 — 버스 원천이라 의미가 다르다")
    void l5_지하철_제외() {
        RouteNameResolver resolver = resolver(stopId -> arrivals(
                new BusArrival("1001", BusCongestionGrade.SATURATED, 10)));

        List<RouteSearchResponse> out = resolver.withRouteNames(List.of(responseOf(subwayLeg())));

        assertNull(out.get(0).legs().get(0).congestionGrade());
    }

    @Test
    @DisplayName("297-L6: 노선이 하나로 정해진 BUS 구간에도 붙는다")
    void l6_단일_노선_구간() {
        RouteNameResolver resolver = resolver(stopId -> arrivals(
                new BusArrival("108", BusCongestionGrade.CONGESTED, 200)));

        List<RouteSearchResponse> out = resolver.withRouteNames(List.of(responseOf(plainBusLeg("108"))));

        RouteLegResponse leg = out.get(0).legs().get(0);
        assertEquals("CONGESTED", leg.congestionGrade());
        assertEquals("108번", leg.routeName(), "기존 노선명 부착은 그대로여야 한다");
    }

    @Test
    @DisplayName("297-L7: 승차 정류소로 조회한다 — 하차 정류소가 아니다")
    void l7_승차_정류소() {
        java.util.List<String> asked = new java.util.ArrayList<>();
        RouteNameResolver resolver = resolver(stopId -> {
            asked.add(stopId);
            return Map.of();
        });

        resolver.withRouteNames(List.of(responseOf(corridorBusLeg())));

        assertEquals(List.of("S1"), asked, "fromNodeId 로만 조회한다");
    }

    @Test
    @DisplayName("297-L8: 조회 함수를 안 주면 기존 동작 그대로 (234 회귀)")
    void l8_조회_없음() {
        RouteNameResolver resolver = new RouteNameResolver(
                ids -> Map.of(),
                ids -> Map.of("108", "108번", "143", "143번"),
                BusRouteIndex.build(busRoutes()),
                ids -> Map.of("108", 10));

        List<RouteSearchResponse> out = resolver.withRouteNames(List.of(responseOf(corridorBusLeg())));

        RouteLegResponse leg = out.get(0).legs().get(0);
        assertNull(leg.congestionGrade());
        assertEquals(2, leg.routeOptions().size(), "옵션 부착은 그대로");
    }

    @Test
    @DisplayName("297-L9: 조회가 터져도 경로 응답은 살아 있다")
    void l9_조회_예외() {
        RouteNameResolver resolver = resolver(stopId -> {
            throw new IllegalStateException("redis down");
        });

        List<RouteSearchResponse> out = resolver.withRouteNames(List.of(responseOf(corridorBusLeg())));

        assertEquals(1, out.size());
        assertNull(out.get(0).legs().get(0).congestionGrade());
    }

    @Test
    @DisplayName("297-L10: BUS 구간의 승차 정류소만 모은다 — prefetch 대상")
    void l10_정류소_수집() {
        Set<String> stops = RouteNameResolver.busBoardingStops(List.of(
                responseOf(corridorBusLeg(), subwayLeg()),
                responseOf(plainBusLeg("108"))));

        assertEquals(Set.of("S1"), stops, "지하철 구간은 빠지고 중복은 합쳐진다");
    }

    @Test
    @DisplayName("297-L11: BUS 구간이 없으면 빈 집합 — 호출 자체가 없다")
    void l11_버스_없음() {
        assertTrue(RouteNameResolver.busBoardingStops(List.of(responseOf(subwayLeg()))).isEmpty());
        assertTrue(RouteNameResolver.busBoardingStops(List.of()).isEmpty());
    }
}
