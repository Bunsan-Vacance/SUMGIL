package com.ssafy.s15p21a104.domain.route.finder;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bus;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder;
import com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorRouteSet;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 비탑승(전부 연결) 1등이 K 후보 수집을 붕괴시키는 버그 회귀 테스트.
 *
 * <p>연결(도보·자전거)만으로 가는 경로가 최단이면 `firstTransitSegment`가 null이 되어
 * 수집 루프가 즉시 멈춘다 — 응답이 1건(자전거 단독)만 나가던 원인.
 */
class RouteConnectionOnlyCandidateTest {

    private static RouteCandidateFinder finder() {
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        for (String id : List.of("PLACE-ORIGIN", "PLACE-DEST", "R1", "R2", "A", "B")) {
            infos.put(id, new RouteMapper.StationInfo(id, id, 37.5, 127.0));
        }
        RaptorRouteSet routeSet = new RaptorRouteSet(List.of(
                new RaptorFinder.Route("B1", TravelMode.BUS, List.of("A", "B"),
                        new int[]{600}, 0)),
                List.of(
                        // 연결만으로 가는 경로: 60 + 120 + 120 = 300초(5분) — 최단.
                        new RaptorFinder.Connection("PLACE-ORIGIN", "R1", 60, TravelMode.WALK),
                        new RaptorFinder.Connection("R1", "R2", 120, TravelMode.BIKE),
                        new RaptorFinder.Connection("R2", "PLACE-DEST", 120, TravelMode.BIKE),
                        // 탑승 경로: 150 + 600 + 150 = 900초(15분) — 대안이어야 한다.
                        new RaptorFinder.Connection("PLACE-ORIGIN", "A", 150, TravelMode.WALK),
                        new RaptorFinder.Connection("B", "PLACE-DEST", 150, TravelMode.WALK)));
        return new RouteCandidateFinder(new TransferRule(0), Map.of(), Set.of(), infos, Map::of,
                BusRouteIndex.build(Map.of()),
                new RouteCandidateFinder.RaptorInput(routeSet, null));
    }

    @Test
    @DisplayName("CN1: 연결 단독 최단이어도 탑승 대안 후보가 함께 나온다")
    void cn1_비탑승최단_대안수집() {
        List<ScoredCandidate> candidates = finder().findCandidatesWithPaths(
                graphOf(bus("A", "B", "B1", 600)), "PLACE-ORIGIN", "PLACE-DEST", 3, null, null);

        assertTrue(candidates.size() >= 2, "후보가 1건뿐이다(비탑승 1등에서 수집 붕괴): " + candidates.size());
        RouteSearchResponse first = candidates.get(0).response();
        assertEquals(300 / 60.0, first.totalMinutes(), 0.02); // 연결 단독이 1등
        assertTrue(candidates.stream().anyMatch(candidate -> candidate.response().legs().stream()
                .anyMatch(leg -> leg.mode() == TravelMode.BUS)), "탑승 대안 후보가 없다");
    }
}
