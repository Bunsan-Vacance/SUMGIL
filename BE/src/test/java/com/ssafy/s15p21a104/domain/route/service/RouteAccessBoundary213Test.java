package com.ssafy.s15p21a104.domain.route.service;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bike;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.walk;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.RouteTestFixtures;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-213 T1 환승 통합 RED.
 * 접근(WALK→주행) 경계는 환승이 아니므로 TRANSFER leg를 만들지 않는다.
 */
class RouteAccessBoundary213Test {

    @Test
    @DisplayName("213-T1: 접근(WALK→BIKE→WALK)은 TRANSFER leg 없이 3개이다")
    void t1_접근경계_TRANSFER없음() {
        RouteSearchService service = RouteTestFixtures.serviceWith(graphOf(
                subway("A", "C", "L1", 900),
                walk("A", "R1", 120),
                bike("R1", "R2", 120),
                walk("R2", "C", 120)), Set.of("R1", "R2"));

        List<RouteSearchResponse> result = service.search("A", "C", null, null, null);

        assertTrue(result.size() >= 1);
        RouteSearchResponse first = result.get(0);
        assertEquals(3, first.legs().size());
        assertEquals(TravelMode.WALK, first.legs().get(0).mode());
        assertEquals(TravelMode.BIKE, first.legs().get(1).mode());
        assertEquals(TravelMode.WALK, first.legs().get(2).mode());
        assertTrue(first.legs().stream().noneMatch(leg -> leg.mode() == TravelMode.TRANSFER));
        assertEquals(0, first.transferCount());
    }
}
