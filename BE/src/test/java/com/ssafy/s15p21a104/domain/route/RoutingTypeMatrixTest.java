package com.ssafy.s15p21a104.domain.route;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bike;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.serviceWith;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.walk;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-138 OD 유형별 라우팅 leg 순서 검증(매트릭스 B 중 역·대여소 축).
 * 정류장·BUS 조합은 S15P21A104-121 인접이라 다루지 않는다. DB·Redis 없이 green.
 */
class RoutingTypeMatrixTest {

    @Test
    @DisplayName("t_역대역_지하철_직통")
    void t_역대역_지하철_직통() {
        List<RouteSearchResponse> r = serviceWith(
                graphOf(subway("A", "C", "L1", 300)), Set.of())
                .search("A", "C", null, null, null);

        assertEquals(1, r.size());
        assertEquals(List.of(TravelMode.SUBWAY), modes(r));
    }

    @Test
    @DisplayName("t_역대역_지하철_환승")
    void t_역대역_지하철_환승() {
        List<RouteSearchResponse> r = serviceWith(
                graphOf(subway("A", "B", "L1", 100), subway("B", "C", "L2", 100)), Set.of())
                .search("A", "C", null, null, null);

        assertEquals(1, r.size());
        assertEquals(List.of(TravelMode.SUBWAY, TravelMode.TRANSFER, TravelMode.SUBWAY), modes(r));
    }

    @Test
    @DisplayName("t_대여소대여소_자전거단독")
    void t_대여소대여소_자전거단독() {
        List<RouteSearchResponse> r = serviceWith(
                graphOf(bike("R1", "R2", 120)), Set.of("R1", "R2"))
                .search("R1", "R2", null, null, null);

        assertEquals(1, r.size());
        assertEquals(List.of(TravelMode.BIKE), modes(r));
    }

    @Test
    @DisplayName("t_역대여소_도보단독")
    void t_역대여소_도보단독() {
        List<RouteSearchResponse> r = serviceWith(
                graphOf(walk("A", "R1", 120)), Set.of("R1"))
                .search("A", "R1", null, null, null);

        assertEquals(1, r.size());
        assertEquals(List.of(TravelMode.WALK), modes(r));
    }

    @Test
    @DisplayName("t_대여소역_도보단독")
    void t_대여소역_도보단독() {
        List<RouteSearchResponse> r = serviceWith(
                graphOf(walk("R1", "A", 120)), Set.of("R1"))
                .search("R1", "A", null, null, null);

        assertEquals(1, r.size());
        assertEquals(List.of(TravelMode.WALK), modes(r));
    }

    @Test
    @DisplayName("t_역대역_자전거우위_도보접근포함")
    void t_역대역_자전거우위_도보접근포함() {
        // 지하철 A→C 900초 vs 도보 A→R1 + 자전거 R1→R2 + 도보 R2→C (접근+환승 포함 540초).
        List<RouteSearchResponse> r = serviceWith(
                graphOf(subway("A", "C", "L1", 900),
                        walk("A", "R1", 60), bike("R1", "R2", 60), walk("R2", "C", 60)),
                Set.of("R1", "R2"))
                .search("A", "C", null, null, null);

        // 185: SUBWAY 전용 조합으로도 (더 느린) 대체 후보가 따로 나온다.
        // 213 T1: 접근 경계는 TRANSFER가 아니다.
        assertTrue(r.size() >= 1);
        assertEquals(List.of(TravelMode.WALK, TravelMode.BIKE, TravelMode.WALK), modes(r));
        assertEquals("A", r.get(0).legs().get(0).fromNodeId());
        assertEquals("R1", r.get(0).legs().get(0).toNodeId());
        assertEquals("R2", r.get(0).legs().get(1).toNodeId());
    }

    @Test
    @DisplayName("t_역대역_자전거복수hop_중간대여소노출")
    void t_역대역_자전거복수hop_중간대여소노출() {
        List<RouteSearchResponse> r = serviceWith(
                graphOf(subway("A", "C", "L1", 1500),
                        walk("A", "R1", 120), bike("R1", "R2", 100),
                        bike("R2", "R3", 100), walk("R3", "C", 120)),
                Set.of("R1", "R2", "R3"))
                .search("A", "C", null, null, null);

        // 185: SUBWAY 전용 조합으로도 (더 느린) 대체 후보가 따로 나온다.
        // 213 T1: 접근 경계는 TRANSFER가 아니다.
        assertTrue(r.size() >= 1);
        assertEquals(List.of(TravelMode.WALK, TravelMode.BIKE,
                TravelMode.BIKE, TravelMode.WALK), modes(r));
        assertEquals("R2", r.get(0).legs().get(1).toNodeId());
        assertEquals("R2", r.get(0).legs().get(2).fromNodeId());
    }

    private List<TravelMode> modes(List<RouteSearchResponse> responses) {
        return responses.get(0).legs().stream().map(RouteLegResponse::mode).toList();
    }
}
