package com.ssafy.s15p21a104.domain.route.geometry;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.global.geo.GeoDistance;
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
                "L1", 5.0, null, "unavailable", null, null, null);
        return new RouteSearchResponse(RouteType.SHORTEST, 5.0, List.of(leg),
                RouteSource.ALGORITHM, null, 0, null);
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

    private static RouteLegResponse walkLegOf(String from, String to) {
        return new RouteLegResponse(TravelMode.WALK,
                from, from, 37.5, 127.0, to, to, 37.5, 127.01,
                "WALK", 1.0, null, "unavailable", null, null, null);
    }

    private static RouteSearchResponse walkResponseOf(String from, String to) {
        return new RouteSearchResponse(RouteType.SHORTEST, 1.0, List.of(walkLegOf(from, to)),
                RouteSource.ALGORITHM, null, 0, null);
    }

    @Test
    @DisplayName("도보 표시 시간: geometry 있으면 폴리라인 실측 기준으로 정정한다")
    void walk표시시간_실측정정() {
        // 두 점 직선 약 880m — 엔진 추정 1.0분과 달라야 한다.
        MultiLineStringResponse geometry = MultiLineStringResponse.of(
                List.of(List.of(List.of(127.0, 37.5), List.of(127.01, 37.5))));
        RouteGeometryEnhancer enhancer = new RouteGeometryEnhancer(
                (routeId, fromLat, fromLng, toLat, toLng) -> Optional.empty(),
                (fromId, toId, fromLat, fromLng, toLat, toLng) -> Optional.of(geometry),
                (fromId, toId, fromLat, fromLng, toLat, toLng) -> Optional.empty());

        List<RouteSearchResponse> result = enhancer.enhanceAll(List.of(walkResponseOf("H", "S")));

        double expectedDist = GeoDistance.haversineMeters(37.5, 127.0, 37.5, 127.01);
        double expectedMin = expectedDist / 67.0;
        assertEquals(expectedMin, result.get(0).legs().get(0).minutes(), 1e-6);
        assertEquals(expectedMin, result.get(0).totalMinutes(), 1e-6);
        assertEquals("available", result.get(0).legs().get(0).geometryStatus());
    }

    @Test
    @DisplayName("도보 표시 시간: geometry 없으면 엔진 값 유지한다 (지어내지 않음)")
    void walk표시시간_무geometry유지() {
        RouteGeometryEnhancer enhancer = new RouteGeometryEnhancer(
                (routeId, fromLat, fromLng, toLat, toLng) -> Optional.empty(),
                (fromId, toId, fromLat, fromLng, toLat, toLng) -> Optional.empty(),
                (fromId, toId, fromLat, fromLng, toLat, toLng) -> Optional.empty());

        List<RouteSearchResponse> result = enhancer.enhanceAll(List.of(walkResponseOf("H", "S")));

        assertEquals(1.0, result.get(0).legs().get(0).minutes(), 1e-9);
        assertEquals(1.0, result.get(0).totalMinutes(), 1e-9);
    }

    @Test
    @DisplayName("동일 좌표 leg는 조회하지 않는다 (0m 접근 왜곡·캐시 오염 방지)")
    void 동일좌표_조회안함() {
        AtomicInteger walkCalls = new AtomicInteger();
        RouteGeometryEnhancer enhancer = new RouteGeometryEnhancer(
                (routeId, fromLat, fromLng, toLat, toLng) -> Optional.empty(),
                (fromId, toId, fromLat, fromLng, toLat, toLng) -> {
                    walkCalls.incrementAndGet();
                    return Optional.of(MultiLineStringResponse.of(
                            List.of(List.of(List.of(127.0, 37.5), List.of(127.01, 37.5)))));
                },
                (fromId, toId, fromLat, fromLng, toLat, toLng) -> Optional.empty());
        RouteLegResponse samePoint = new RouteLegResponse(TravelMode.WALK,
                "N", "N", 37.5, 127.0, "N", "N", 37.5, 127.0,
                "WALK", 0.0, null, "unavailable", null, null, null);
        RouteSearchResponse input = new RouteSearchResponse(RouteType.SHORTEST, 0.0,
                List.of(samePoint), RouteSource.ALGORITHM, null, 0, null);

        List<RouteSearchResponse> result = enhancer.enhanceAll(List.of(input));

        assertEquals(0, walkCalls.get());
        assertEquals("unavailable", result.get(0).legs().get(0).geometryStatus());
        assertEquals(0.0, result.get(0).legs().get(0).minutes(), 1e-9);
        assertEquals(0.0, result.get(0).totalMinutes(), 1e-9);
    }
}
