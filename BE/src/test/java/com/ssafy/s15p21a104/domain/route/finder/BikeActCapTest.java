package com.ssafy.s15p21a104.domain.route.finder;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bike;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 대여 1회(연속 BIKE) 상한 테스트(5부 T3) — 상한(240초 = 1km/15km·h⁻¹)을 넘는 연속 자전거
 * 구간은 후보에서 제외된다. 레거시 폴백 경로에서도 방어한다.
 */
class BikeActCapTest {

    private static RouteCandidateFinder finder() {
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        for (String id : List.of("A", "B", "C")) {
            infos.put(id, new RouteMapper.StationInfo(id, id, 37.5, 127.0));
        }
        return new RouteCandidateFinder(new TransferRule(0), Map.of(), Set.of(), infos, Map::of,
                BusRouteIndex.build(Map.of()));
    }

    @Test
    @DisplayName("C1: 연속 자전거 260초(>240) 경로는 후보에서 제외된다")
    void c1_상한초과_제외() {
        var graph = graphOf(bike("A", "B", 130), bike("B", "C", 130));

        List<ScoredCandidate> candidates =
                finder().findCandidatesWithPaths(graph, "A", "C", 3, null, null);

        assertTrue(candidates.isEmpty(), "상한 초과 자전거 경로가 남았다");
    }

    @Test
    @DisplayName("C2: 연속 자전거 220초(≤240) 경로는 유지된다")
    void c2_상한이내_유지() {
        var graph = graphOf(bike("A", "B", 110), bike("B", "C", 110));

        List<ScoredCandidate> candidates =
                finder().findCandidatesWithPaths(graph, "A", "C", 3, null, null);

        assertFalse(candidates.isEmpty(), "상한 이내 자전거 경로가 사라졌다");
    }
}
