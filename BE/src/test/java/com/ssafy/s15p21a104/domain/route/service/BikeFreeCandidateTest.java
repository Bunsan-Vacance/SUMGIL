package com.ssafy.s15p21a104.domain.route.service;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.RouteCandidateFinder;
import com.ssafy.s15p21a104.domain.route.finder.ScoredCandidate;
import com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorFinder;
import com.ssafy.s15p21a104.domain.route.finder.raptor.RaptorRouteSet;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * "자전거 없는 대중교통 후보 1개 보장" 테스트(2026-09-22) — 역삼→한티(prod)처럼 자전거·버스
 * 혼합 후보가 슬롯을 채워 전 구간 지하철 후보가 6건 밖으로 밀리는 경우를 보정한다.
 *
 * <p>2026-09-22 보강: 주입한 후보의 원본 경로({@link ScoredCandidate})를 함께 돌려준다 —
 * 응답 계약 채점(링크 혼잡)이 이 후보만 노선 통계로 폴백하던 결함을 막는다.
 */
class BikeFreeCandidateTest {

    private static RouteSearchResponse response(RouteType type, double minutes, TravelMode mode) {
        RouteLegResponse leg = new RouteLegResponse(mode, "A", "A", 37.5, 127.0,
                "C", "C", 37.5, 127.1, mode.name(), minutes, null, "unavailable", null, null, null);
        return new RouteSearchResponse(type, minutes, List.of(leg), RouteSource.ALGORITHM,
                null, 0, null);
    }

    private static RouteCandidateFinder finder() {
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        for (String id : List.of("A", "C")) {
            infos.put(id, new RouteMapper.StationInfo(id, id, 37.5, 127.0));
        }
        RaptorRouteSet routeSet = new RaptorRouteSet(List.of(
                new RaptorFinder.Route("L1", TravelMode.SUBWAY, List.of("A", "C"),
                        new int[]{600}, 0)), List.of());
        return new RouteCandidateFinder(new TransferRule(0), Map.of(), Set.of(), infos, Map::of,
                BusRouteIndex.build(Map.of()),
                new RouteCandidateFinder.RaptorInput(routeSet, null));
    }

    @Test
    @DisplayName("BF1: 6건이 전부 자전거 포함이면 대중교통 전용 후보로 마지막 대안을 대체한다")
    void bf1_대체() {
        List<RouteSearchResponse> six = new ArrayList<>();
        six.add(response(RouteType.SHORTEST, 5, TravelMode.BIKE));
        for (int i = 0; i < 4; i++) {
            six.add(response(RouteType.ALTERNATIVE, 6 + i, TravelMode.BIKE));
        }
        six.add(response(RouteType.LOW_CONGESTION, 11, TravelMode.BIKE));

        RouteSearchService.Injection out = RouteSearchService.ensureBikeFreeCandidate(
                six, finder(), graphOf(), "A", "C", null);

        assertEquals(6, out.six().size());
        assertTrue(out.six().stream().anyMatch(r -> r.legs().stream()
                        .anyMatch(l -> l.mode() == TravelMode.SUBWAY)
                        && r.legs().stream().noneMatch(l -> l.mode() == TravelMode.BIKE)),
                "대중교통 전용 후보가 없다: " + out.six().stream().map(RouteSearchResponse::routeType).toList());
    }

    @Test
    @DisplayName("BF2: 주입 후보는 원본 경로(엣지)를 함께 돌려준다 — 링크 채점 입력 보존")
    void bf2_주입후보_엣지보존() {
        List<RouteSearchResponse> six = new ArrayList<>();
        six.add(response(RouteType.SHORTEST, 5, TravelMode.BIKE));
        for (int i = 0; i < 4; i++) {
            six.add(response(RouteType.ALTERNATIVE, 6 + i, TravelMode.BIKE));
        }
        six.add(response(RouteType.LOW_CONGESTION, 11, TravelMode.BIKE));

        RouteSearchService.Injection out = RouteSearchService.ensureBikeFreeCandidate(
                six, finder(), graphOf(), "A", "C", null);

        assertEquals(1, out.injected().size(), "주입 후보 1건이 원본 경로와 함께 돌아와야 한다");
        ScoredCandidate injected = out.injected().get(0);
        assertTrue(!injected.path().edges().isEmpty(), "주입 후보의 원본 엣지가 비어 있다");
        String injectedSignature = RouteCandidateFinder.exactSignature(injected.response());
        assertTrue(out.six().stream()
                        .anyMatch(r -> RouteCandidateFinder.exactSignature(r).equals(injectedSignature)),
                "주입 후보가 6건 안에 실제로 반영되지 않았다");
    }

    @Test
    @DisplayName("BF3: 이미 대중교통 전용 후보가 있으면 변경하지 않는다")
    void bf3_유지() {
        List<RouteSearchResponse> six = List.of(
                response(RouteType.SHORTEST, 5, TravelMode.BIKE),
                response(RouteType.ALTERNATIVE, 9, TravelMode.SUBWAY));

        RouteSearchService.Injection out = RouteSearchService.ensureBikeFreeCandidate(
                six, finder(), graphOf(), "A", "C", null);

        assertSame(six, out.six());
        assertTrue(out.injected().isEmpty());
    }

    @Test
    @DisplayName("BF4: 자전거만 허용이면 보장 대상이 없다(변경 없음)")
    void bf4_자전거만() {
        List<RouteSearchResponse> six = List.of(response(RouteType.SHORTEST, 5, TravelMode.BIKE));

        RouteSearchService.Injection out = RouteSearchService.ensureBikeFreeCandidate(
                six, finder(), graphOf(), "A", "C", List.of(TravelMode.BIKE));

        assertSame(six, out.six());
        assertTrue(out.injected().isEmpty());
    }

    @Test
    @DisplayName("BF5: 지하철 후보가 없으면 자전거 없는 대중교통(버스) 후보로 대체한다")
    void bf5_버스폴백() {
        List<RouteSearchResponse> six = new ArrayList<>();
        six.add(response(RouteType.SHORTEST, 5, TravelMode.BIKE));
        for (int i = 0; i < 4; i++) {
            six.add(response(RouteType.ALTERNATIVE, 6 + i, TravelMode.BIKE));
        }
        six.add(response(RouteType.LOW_CONGESTION, 11, TravelMode.BIKE));

        RouteSearchService.Injection out = RouteSearchService.ensureBikeFreeCandidate(
                six, busFinder(), graphOf(), "A", "C", null);

        assertEquals(6, out.six().size());
        assertTrue(out.six().stream().anyMatch(r -> r.legs().stream()
                        .anyMatch(l -> l.mode() == TravelMode.BUS)
                        && r.legs().stream().noneMatch(l -> l.mode() == TravelMode.BIKE)),
                "자전거 없는 대중교통 후보가 없다");
        assertEquals(1, out.injected().size());
    }

    @Test
    @DisplayName("BF6: 지하철은 없지만 자전거 없는 대중교통 후보가 이미 있으면 변경하지 않는다")
    void bf6_이미대중교통() {
        List<RouteSearchResponse> six = List.of(
                response(RouteType.SHORTEST, 5, TravelMode.BIKE),
                response(RouteType.ALTERNATIVE, 12, TravelMode.BUS));

        RouteSearchService.Injection out = RouteSearchService.ensureBikeFreeCandidate(
                six, busFinder(), graphOf(), "A", "C", null);

        assertSame(six, out.six());
        assertTrue(out.injected().isEmpty());
    }

    private static RouteCandidateFinder busFinder() {
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        for (String id : List.of("A", "C")) {
            infos.put(id, new RouteMapper.StationInfo(id, id, 37.5, 127.0));
        }
        RaptorRouteSet routeSet = new RaptorRouteSet(List.of(
                new RaptorFinder.Route("B9", TravelMode.BUS, List.of("A", "C"),
                        new int[]{600}, 0)), List.of());
        return new RouteCandidateFinder(new TransferRule(0), Map.of(), Set.of(), infos, Map::of,
                BusRouteIndex.build(Map.of()),
                new RouteCandidateFinder.RaptorInput(routeSet, null));
    }
}
