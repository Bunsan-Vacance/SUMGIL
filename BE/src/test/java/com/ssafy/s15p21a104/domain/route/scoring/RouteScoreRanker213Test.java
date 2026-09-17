package com.ssafy.s15p21a104.domain.route.scoring;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * S15P21A104-213 T4 스코어링 분리 RED.
 * 혼잡도 점수 조회 함수를 주입받아 COMFORT 재정렬을 수행한다.
 */
class RouteScoreRanker213Test {

    private static RouteSearchResponse responseOf(String routeId, double minutes) {
        RouteLegResponse leg = new RouteLegResponse(TravelMode.SUBWAY,
                "A", "에이역", 37.5, 127.0, "C", "씨역", 37.5, 127.01,
                routeId, minutes, null, "unavailable", null, null);
        return new RouteSearchResponse(RouteType.SHORTEST, minutes, List.of(leg),
                RouteSource.ALGORITHM, null, 0);
    }

    @Test
    @DisplayName("213-T4: 혼잡도 가장 낮은 후보가 LOW_CONGESTION으로 맨 앞에 온다")
    void t4_쾌적재정렬() {
        RouteScoreRanker ranker = new RouteScoreRanker(
                (targetType, targetId, dowType, timeSlot) -> switch (targetId) {
                    case "L1" -> 4.0;
                    case "L2" -> 1.0;
                    default -> null;
                });
        List<RouteSearchResponse> input = List.of(
                responseOf("L1", 5.0), responseOf("L2", 8.0));

        List<RouteSearchResponse> result = ranker.applyComfort(
                input, 0, 17);

        assertEquals(2, result.size());
        assertEquals(RouteType.LOW_CONGESTION, result.get(0).routeType());
        assertEquals("L2", result.get(0).legs().get(0).routeId());
        assertEquals(8.0, result.get(0).totalMinutes());
    }

    @Test
    @DisplayName("213-T4: 혼잡도 데이터 없으면 순서를 건드리지 않는다")
    void t4_데이터없음_유지() {
        RouteScoreRanker ranker = new RouteScoreRanker(
                (targetType, targetId, dowType, timeSlot) -> null);
        List<RouteSearchResponse> input = List.of(
                responseOf("L1", 5.0), responseOf("L2", 8.0));

        List<RouteSearchResponse> result = ranker.applyComfort(
                input, 0, 17);

        assertEquals(input, result);
    }

    @Test
    @DisplayName("213-T4: SUBWAY 없으면 그대로 둔다")
    void t4_SUBWAY없음_유지() {
        RouteLegResponse leg = new RouteLegResponse(TravelMode.BIKE,
                "A", "에이역", 37.5, 127.0, "C", "씨역", 37.5, 127.01,
                "BIKE", 5.0, null, "unavailable", null, null);
        RouteSearchResponse bike = new RouteSearchResponse(
                RouteType.SHORTEST, 5.0, List.of(leg), RouteSource.ALGORITHM, null, 0);
        RouteScoreRanker ranker = new RouteScoreRanker(
                (targetType, targetId, dowType, timeSlot) -> 1.0);

        List<RouteSearchResponse> result = ranker.applyComfort(
                List.of(bike), 0, 17);

        assertEquals(1, result.size());
        assertEquals(RouteType.SHORTEST, result.get(0).routeType());
    }
}
