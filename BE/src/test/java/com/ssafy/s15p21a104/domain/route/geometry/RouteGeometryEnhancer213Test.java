package com.ssafy.s15p21a104.domain.route.geometry;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-213 T3 geometry 비동기 RED.
 * 후보별 geometry 후처리가 순서 보장 + 실패 격리(한 후보 실패가 전체를 깨지 않음)되어야 한다.
 */
class RouteGeometryEnhancer213Test {

    private static RouteSearchResponse responseOf(String id) {
        RouteLegResponse leg = new RouteLegResponse(TravelMode.SUBWAY,
                id, id + "역", 37.5, 127.0, id + "-2", id + "-2역", 37.5, 127.01,
                "L1", 5.0, null, "unavailable", null, null);
        return new RouteSearchResponse(RouteType.SHORTEST, 5.0, List.of(leg),
                RouteSource.ALGORITHM, null, 0);
    }

    @Test
    @DisplayName("213-T3: 후보 순서를 유지한 채 geometry를 붙인다")
    void t3_순서유지() {
        RouteGeometryEnhancer enhancer = new RouteGeometryEnhancer(
                (routeId, fromLat, fromLng, toLat, toLng) -> Optional.empty(),
                (fromId, toId, fromLat, fromLng, toLat, toLng) -> Optional.empty(),
                (fromId, toId, fromLat, fromLng, toLat, toLng) -> Optional.empty());
        List<RouteSearchResponse> input = List.of(responseOf("A"), responseOf("B"), responseOf("C"));

        List<RouteSearchResponse> result = enhancer.enhanceAll(input);

        assertEquals(3, result.size());
        assertEquals("A", result.get(0).legs().get(0).fromNodeId());
        assertEquals("B", result.get(1).legs().get(0).fromNodeId());
        assertEquals("C", result.get(2).legs().get(0).fromNodeId());
    }

    @Test
    @DisplayName("213-T3: 한 후보 geometry 실패가 다른 후보를 깨지 않는다")
    void t3_실패격리() {
        AtomicInteger calls = new AtomicInteger();
        RouteGeometryEnhancer enhancer = new RouteGeometryEnhancer(
                (routeId, fromLat, fromLng, toLat, toLng) -> {
                    calls.incrementAndGet();
                    if ("L1".equals(routeId) && fromLat == 37.5) {
                        throw new RuntimeException("rail down");
                    }
                    return Optional.empty();
                },
                (fromId, toId, fromLat, fromLng, toLat, toLng) -> Optional.empty(),
                (fromId, toId, fromLat, fromLng, toLat, toLng) -> Optional.empty());
        List<RouteSearchResponse> input = List.of(responseOf("A"), responseOf("B"));

        List<RouteSearchResponse> result = enhancer.enhanceAll(input);

        assertEquals(2, result.size());
        assertTrue(result.stream().allMatch(r -> r.legs().get(0).geometryStatus().equals("unavailable")));
    }

    @Test
    @DisplayName("213-T3: geometry 있으면 available + 거리 합산")
    void t3_geometry있음_available() {
        MultiLineStringResponse geometry = MultiLineStringResponse.of(
                List.of(List.of(List.of(127.0, 37.5), List.of(127.01, 37.5))));
        RouteGeometryEnhancer enhancer = new RouteGeometryEnhancer(
                (routeId, fromLat, fromLng, toLat, toLng) -> Optional.of(geometry),
                (fromId, toId, fromLat, fromLng, toLat, toLng) -> Optional.empty(),
                (fromId, toId, fromLat, fromLng, toLat, toLng) -> Optional.empty());

        List<RouteSearchResponse> result = enhancer.enhanceAll(List.of(responseOf("A")));

        assertEquals(1, result.size());
        assertEquals("available", result.get(0).legs().get(0).geometryStatus());
        assertTrue(result.get(0).legs().get(0).distanceMeters() > 0);
        assertEquals(result.get(0).legs().get(0).distanceMeters(),
                result.get(0).totalDistanceMeters());
    }
}
