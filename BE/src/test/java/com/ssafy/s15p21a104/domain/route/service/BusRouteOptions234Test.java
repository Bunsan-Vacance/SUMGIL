package com.ssafy.s15p21a104.domain.route.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder.RouteStop;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class BusRouteOptions234Test {

    private static Map<String, List<RouteStop>> busRoutes() {
        return Map.of(
                "108", List.of(
                        new RouteStop("S1", 1, 37.5000, 127.0000),
                        new RouteStop("S2", 2, 37.5000, 127.0050)),
                "143", List.of(
                        new RouteStop("S1", 1, 37.5000, 127.0000),
                        new RouteStop("S2", 2, 37.5000, 127.0050)));
    }

    private static RouteLegResponse busLeg() {
        return new RouteLegResponse(TravelMode.BUS,
                "S1", "정류장1", 37.5, 127.0, "S2", "정류장2", 37.5, 127.01,
                BusEdgeBuilder.BUS_CORRIDOR_ROUTE_ID, 4.0, null, "unavailable", null, null, null);
    }

    private static RouteSearchResponse responseOf(RouteLegResponse leg) {
        return new RouteSearchResponse(RouteType.SHORTEST, 4.0, List.of(leg),
                RouteSource.ALGORITHM, null, 0, null);
    }

    @Test
    @DisplayName("234-T40: 정규 BUS leg에 옵션·이름·headway가 붙는다")
    void t40_옵션부착() {
        RouteNameResolver resolver = new RouteNameResolver(
                ids -> Map.of(),
                ids -> Map.of("108", "108번", "143", "143번"),
                BusRouteIndex.build(busRoutes()),
                ids -> Map.of("108", 10));

        List<RouteSearchResponse> out =
                resolver.withRouteNames(List.of(responseOf(busLeg())));

        assertEquals(1, out.size());
        RouteLegResponse leg = out.get(0).legs().get(0);
        assertNull(leg.routeName());
        assertEquals(2, leg.routeOptions().size());
        assertEquals("108", leg.routeOptions().get(0).routeId());
        assertEquals("108번", leg.routeOptions().get(0).routeName());
        assertEquals(10, leg.routeOptions().get(0).headwayMin());
        assertEquals("143", leg.routeOptions().get(1).routeId());
        assertNull(leg.routeOptions().get(1).headwayMin());
    }

    @Test
    @DisplayName("234-T41: 旧 BUS leg(routeId 실값)는 기존 경로 그대로다")
    void t41_구경로유지() {
        RouteLegResponse legacy = new RouteLegResponse(TravelMode.BUS,
                "S1", "정류장1", 37.5, 127.0, "S2", "정류장2", 37.5, 127.01,
                "B100", 4.0, null, "unavailable", null, "100번", null);
        RouteNameResolver resolver = new RouteNameResolver(
                ids -> Map.of(), ids -> Map.of("B100", "100번"));

        List<RouteSearchResponse> out =
                resolver.withRouteNames(List.of(responseOf(legacy)));

        assertEquals("100번", out.get(0).legs().get(0).routeName());
        assertNull(out.get(0).legs().get(0).routeOptions());
    }
}
