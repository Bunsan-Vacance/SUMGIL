package com.ssafy.s15p21a104.domain.route.finder;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder;
import com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorRouteSet;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 탑승 대기 분리 계약(2026-09-22) — leg 소요({@code minutes})는 이동만, 대기는
 * {@code waitMinutes}로 분리한다. 총 소요 시간은 대기를 포함한 채 유지된다(합 불변식).
 */
class RouteWaitSplitTest {

    private static final List<String> NODES = List.of("A", "B", "D");

    private static RouteCandidateFinder finder(RaptorRouteSet routeSet) {
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        for (String id : NODES) {
            infos.put(id, new RouteMapper.StationInfo(id, id, 37.5, 127.0));
        }
        return new RouteCandidateFinder(new TransferRule(180), Map.of(), Set.of(), infos, Map::of,
                BusRouteIndex.build(Map.of()),
                new RouteCandidateFinder.RaptorInput(routeSet, null));
    }

    @Test
    @DisplayName("W1: 두 번 탑승해도 leg 분은 이동만, 대기는 waitMinutes로 분리된다")
    void w1_대기_분리() {
        RaptorRouteSet routeSet = new RaptorRouteSet(List.of(
                new RaptorFinder.Route("s1", TravelMode.SUBWAY, List.of("A", "B"), new int[]{100}, 30),
                new RaptorFinder.Route("s2", TravelMode.SUBWAY, List.of("B", "D"), new int[]{100}, 45)),
                List.of());

        List<ScoredCandidate> candidates = finder(routeSet)
                .findCandidatesWithPaths(graphOf(), "A", "D", 1, null, null);

        assertTrue(!candidates.isEmpty(), "RAPTOR 후보가 없다");
        RouteSearchResponse best = candidates.get(0).response();
        // 이동 200 + 대기 75 + 환승 180(B 환승역) = 455
        assertEquals(455 / 60.0, best.totalMinutes(), 0.02);

        RouteLegResponse first = best.legs().get(0);
        assertEquals(TravelMode.SUBWAY, first.mode());
        assertEquals(100 / 60.0, first.minutes(), 0.02);
        assertEquals(Double.valueOf(30 / 60.0), first.waitMinutes());

        RouteLegResponse last = best.legs().get(best.legs().size() - 1);
        assertEquals(TravelMode.SUBWAY, last.mode());
        assertEquals(100 / 60.0, last.minutes(), 0.02);
        assertEquals(Double.valueOf(45 / 60.0), last.waitMinutes());

        double sum = best.legs().stream()
                .mapToDouble(leg -> leg.minutes() + (leg.waitMinutes() == null ? 0 : leg.waitMinutes()))
                .sum();
        assertEquals(best.totalMinutes(), sum, 0.02, "leg 합 + 대기 = 총계 불변식");
    }
}
