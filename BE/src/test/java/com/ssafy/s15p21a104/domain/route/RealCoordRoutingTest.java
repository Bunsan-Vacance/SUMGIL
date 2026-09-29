package com.ssafy.s15p21a104.domain.route;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.serviceWith;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bike.BikeEdgeBuilder.Stop;
import com.ssafy.s15p21a104.domain.route.bike.BikeRentalEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.loader.RouteEdgeRow;
import com.ssafy.s15p21a104.domain.route.loader.RouteGraphLoader;
import com.ssafy.s15p21a104.domain.route.loader.RouteGraphRawData;
import com.ssafy.s15p21a104.domain.route.walk.WalkEdgeBuilder;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-139 실좌표 골든 라우팅. 실DB에서 읽은 실측 좌표를 상수로 고정해, 거리·환승 페널티가
 * 만드는 실제 경로 선택과 대여소 노출을 검증한다. 좌표만 쓰므로 DB·Redis 없이 green.
 *
 * <p>출처: S15P21A104-122 런타임 실측(2026-09-11), incidents/2026-09-11-bike-route-rental-gap.md.
 */
class RealCoordRoutingTest {

    @Test
    @DisplayName("t_미아수유_자전거경로_대여소노출")
    void t_미아수유_자전거경로_대여소노출() {
        // 415 미아 → S115 수유. 대여소 ST-948(미아역) → ST-1391(수유) 자전거 이동이 최단.
        Map<String, Stop> stations = Map.of(
                "415", new Stop("415", 37.626435, 127.026151),
                "S115", new Stop("S115", 37.62706, 127.01817));
        Map<String, Stop> rentals = Map.of(
                "ST-948", new Stop("ST-948", 37.62607956, 127.02648163),
                "ST-1391", new Stop("ST-1391", 37.62652969, 127.01805878));
        List<Edge> extra = new ArrayList<>();
        extra.addAll(WalkEdgeBuilder.build(stations, rentals));
        extra.addAll(BikeRentalEdgeBuilder.build(rentals));
        RouteGraph graph = RouteGraphLoader.load(
                new RouteGraphRawData(
                        List.of(new RouteEdgeRow("415", "S115", "1004", 900, 0)),
                        Map.of("415", "미아", "S115", "수유"), Map.of("1004", "4호선")),
                extra).graph();

        var result = serviceWith(graph, Set.of("ST-948", "ST-1391"))
                .search("415", "S115", null, null, null);

        // 185: SUBWAY 전용 조합으로도 (더 느린) 직통 대체 후보가 따로 나온다.
        // 213 T1: 접근(WALK ↔ BIKE) 경계는 TRANSFER가 아니다.
        assertTrue(result.size() >= 1);
        List<TravelMode> modes = result.get(0).legs().stream()
                .map(com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse::mode).toList();
        assertEquals(List.of(TravelMode.WALK, TravelMode.BIKE, TravelMode.WALK), modes);
        assertEquals("ST-948", result.get(0).legs().get(0).toNodeId());
        assertEquals("ST-1391", result.get(0).legs().get(1).toNodeId());
    }

    @Test
    @DisplayName("t_삼전일원_지하철최단")
    void t_삼전일원_지하철최단() {
        // 4131 삼전 → 338 일원. 대여소 간 직접 이동이 불가해 지하철이 최단(PoC 최단 로직).
        Map<String, Stop> stations = Map.of(
                "4131", new Stop("4131", 37.504531, 127.087211),
                "338", new Stop("338", 37.48389, 127.08416));
        Map<String, Stop> rentals = Map.of(
                "ST-1728", new Stop("ST-1728", 37.50471115, 127.08756256),
                "ST-822", new Stop("ST-822", 37.4833107, 127.08493805));
        List<Edge> extra = new ArrayList<>();
        extra.addAll(WalkEdgeBuilder.build(stations, rentals));
        extra.addAll(BikeRentalEdgeBuilder.build(rentals));
        RouteGraph graph = RouteGraphLoader.load(
                new RouteGraphRawData(
                        List.of(new RouteEdgeRow("4131", "338", "1009", 300, 0)),
                        Map.of("4131", "삼전", "338", "일원"), Map.of("1009", "9호선")),
                extra).graph();

        var result = serviceWith(graph, Set.of("ST-1728", "ST-822"))
                .search("4131", "338", null, null, null);

        assertEquals(1, result.size());
        List<TravelMode> modes = result.get(0).legs().stream()
                .map(com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse::mode).toList();
        assertTrue(modes.contains(TravelMode.SUBWAY));
        assertTrue(!modes.contains(TravelMode.BIKE));
    }
}
