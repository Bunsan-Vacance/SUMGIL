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
 * S15P21A104-138 modes 필터 매트릭스(매트릭스 C 중 BUS 제외). DB·Redis 없이 green.
 *
 * <p>F2는 현행 정책(K=1 최단 + 사후 필터)을 그대로 기대값으로 기록한다 — 최단이 지하철이면
 * BIKE 요청은 빈 배열이다({@code decisions/week1-subway-poc.md} 후보 수 K=1).
 */
class ModeFilterMatrixTest {

    @Test
    @DisplayName("F1: modes=SUBWAY, 지하철 최단이면 SUBWAY 반환")
    void f1_subway요청_지하철최단() {
        List<RouteSearchResponse> r = serviceWith(
                graphOf(subway("A", "C", "L1", 300)), Set.of())
                .search("A", "C", List.of(TravelMode.SUBWAY), null, null);

        assertEquals(1, r.size());
        assertEquals(List.of(TravelMode.SUBWAY), modes(r));
    }

    @Test
    @DisplayName("F2: modes=BIKE, 지하철 최단이면 빈 배열(사후 필터)")
    void f2_bike요청_지하철최단_빈배열() {
        List<RouteSearchResponse> r = serviceWith(
                graphOf(subway("A", "C", "L1", 300)), Set.of())
                .search("A", "C", List.of(TravelMode.BIKE), null, null);

        assertTrue(r.isEmpty());
    }

    @Test
    @DisplayName("F4: modes=WALK, 도보 최단이면 WALK 반환")
    void f4_walk요청_도보최단() {
        List<RouteSearchResponse> r = serviceWith(
                graphOf(walk("A", "R1", 120)), Set.of("R1"))
                .search("A", "R1", List.of(TravelMode.WALK), null, null);

        assertEquals(1, r.size());
        assertEquals(List.of(TravelMode.WALK), modes(r));
    }

    @Test
    @DisplayName("F5: modes=SUBWAY,BIKE, 자전거 최단이면 자전거 경로 반환(WALK 접근 통과)")
    void f5_subwaybike요청_자전거최단() {
        List<RouteSearchResponse> r = serviceWith(
                graphOf(subway("A", "C", "L1", 900),
                        walk("A", "R1", 60), bike("R1", "R2", 60), walk("R2", "C", 60)),
                Set.of("R1", "R2"))
                .search("A", "C", List.of(TravelMode.SUBWAY, TravelMode.BIKE), null, null);

        assertEquals(1, r.size());
        assertTrue(modes(r).contains(TravelMode.BIKE));
    }

    @Test
    @DisplayName("F6: modes=전체, 지하철 최단이면 SUBWAY 반환")
    void f6_전체모드_지하철최단() {
        List<RouteSearchResponse> r = serviceWith(
                graphOf(subway("A", "C", "L1", 300)), Set.of())
                .search("A", "C",
                        List.of(TravelMode.WALK, TravelMode.BIKE, TravelMode.BUS, TravelMode.SUBWAY),
                        null, null);

        assertEquals(1, r.size());
        assertEquals(List.of(TravelMode.SUBWAY), modes(r));
    }

    @Test
    @DisplayName("F7: modes=null, 지하철 최단이면 SUBWAY 반환")
    void f7_모드미지정_지하철최단() {
        List<RouteSearchResponse> r = serviceWith(
                graphOf(subway("A", "C", "L1", 300)), Set.of())
                .search("A", "C", null, null, null);

        assertEquals(1, r.size());
        assertEquals(List.of(TravelMode.SUBWAY), modes(r));
    }

    @Test
    @DisplayName("F8: modes=빈 목록, 전체 허용 취급")
    void f8_빈목록_전체허용() {
        List<RouteSearchResponse> r = serviceWith(
                graphOf(subway("A", "C", "L1", 300)), Set.of())
                .search("A", "C", List.of(), null, null);

        assertEquals(1, r.size());
        assertEquals(List.of(TravelMode.SUBWAY), modes(r));
    }

    private List<TravelMode> modes(List<RouteSearchResponse> responses) {
        return responses.get(0).legs().stream().map(RouteLegResponse::mode).toList();
    }
}
