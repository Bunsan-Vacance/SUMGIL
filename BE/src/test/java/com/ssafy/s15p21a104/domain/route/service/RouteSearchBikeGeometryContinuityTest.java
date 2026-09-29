package com.ssafy.s15p21a104.domain.route.service;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bike;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ssafy.s15p21a104.domain.route.RouteTestFixtures;
import com.ssafy.s15p21a104.domain.route.bike.geometry.BikeGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry;
import com.ssafy.s15p21a104.domain.route.geometry.RailGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/**
 * S15P21A104-153: 자전거 구간 지오메트리 조회 검증(FE-자전거-연속구간-경로선-연결-수정요청.md).
 *
 * <p>로드맵 1단계(2026-09-22)로 BIKE는 <b>대여~반납 1 leg</b>다 — 전체 구간(B→C)을 1회 조회해
 * 그 leg에 싣는다(대여소 단위 분할 호출 없음). 조회 실패 시 임의 직선을 만들지 않는다.
 */
@ExtendWith(MockitoExtension.class)
class RouteSearchBikeGeometryContinuityTest {

    @Mock
    private StationRepository stationRepository;

    @Mock
    private RouteGraphRegistry graphRegistry;

    @Mock
    private BikeGeometryRegistry bikeGeometryRegistry;

    private RouteSearchService routeSearchService;

    @BeforeEach
    void setUp() {
        Station stationB = RouteTestFixtures.mockStation("B", "비역");
        Station stationC = RouteTestFixtures.mockStation("C", "씨역");
        lenient().when(stationRepository.findById("B")).thenReturn(Optional.of(stationB));
        lenient().when(stationRepository.findById("C")).thenReturn(Optional.of(stationC));

        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        infos.put("B", new RouteMapper.StationInfo("B", "비역", 37.5000, 127.0000));
        infos.put("R1", new RouteMapper.StationInfo("R1", "대여소1", 37.5010, 127.0010));
        infos.put("C", new RouteMapper.StationInfo("C", "씨역", 37.5020, 127.0020));
        lenient().when(graphRegistry.stationInfos()).thenReturn(infos);
        lenient().when(graphRegistry.rentalIds()).thenReturn(Set.of("R1"));
        lenient().when(graphRegistry.transferTimes()).thenReturn(Map.of());
        lenient().when(graphRegistry.bikeStock()).thenReturn(Map.of());
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                bike("B", "R1", 120),
                bike("R1", "C", 120)));
        lenient().when(graphRegistry.graphFor(
                org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.anyInt()))
                .thenAnswer(invocation -> graphRegistry.graph());

        // B→C 전체 구간 1회 조회 결과: 중간점이 R1 좌표와 정확히 일치하는 연속 좌표열.
        MultiLineStringResponse wholeRun = MultiLineStringResponse.of(List.of(List.of(
                List.of(127.0000, 37.5000),
                List.of(127.0010, 37.5010),
                List.of(127.0020, 37.5020))));
        lenient().when(bikeGeometryRegistry.geometryFor(
                        eq("B"), eq("C"), anyDouble(), anyDouble(), anyDouble(), anyDouble()))
                .thenReturn(Optional.of(wholeRun));

        routeSearchService = new RouteSearchService(
                stationRepository, graphRegistry, new TransferRule(180),
                new RailGeometryRegistry(null, null), RouteTestFixtures.noopWalkGeometryRegistry(),
                bikeGeometryRegistry,
                RouteTestFixtures.noopRouteLineRepository(), RouteTestFixtures.noopBusRouteRepository(),
                RouteTestFixtures.noopCongestionRepository(),
                RouteTestFixtures.noopCongestionPredRepository());
    }

    @Test
    @DisplayName("153-T1: BIKE는 대여~반납 1 leg — 전체 구간 1회 조회 결과를 싣는다")
    void t153_연속_BIKE_전체구간_1leg() {
        List<RouteSearchResponse> result = routeSearchService.search("B", "C", null, null, null);

        RouteSearchResponse candidate = result.stream()
                .filter(r -> r.legs().size() == 1)
                .findFirst().orElseThrow();
        RouteLegResponse leg = candidate.legs().get(0);

        assertEquals(TravelMode.BIKE, leg.mode());
        assertEquals("B", leg.fromNodeId());
        assertEquals("C", leg.toNodeId());
        assertTrue(leg.geometry() != null, "전체 구간 지오메트리가 실려야 한다");

        // B→C 전체 구간은 1회만 조회한다(대여소 단위 분할 호출 없음).
        verify(bikeGeometryRegistry, never()).geometryFor(
                eq("B"), eq("R1"), anyDouble(), anyDouble(), anyDouble(), anyDouble());
        verify(bikeGeometryRegistry, never()).geometryFor(
                eq("R1"), eq("C"), anyDouble(), anyDouble(), anyDouble(), anyDouble());
    }

    @Test
    @DisplayName("153-T2: 조회 실패 시 임의 직선을 만들지 않고 원본 leg를 유지한다")
    void t153_조회실패시_원본유지() {
        BikeGeometryRegistry failingRegistry = mock(BikeGeometryRegistry.class);
        when(failingRegistry.geometryFor(eq("B"), eq("C"), anyDouble(), anyDouble(), anyDouble(), anyDouble()))
                .thenReturn(Optional.empty());
        RouteSearchService service = new RouteSearchService(
                stationRepository, graphRegistry, new TransferRule(180),
                new RailGeometryRegistry(null, null), RouteTestFixtures.noopWalkGeometryRegistry(),
                failingRegistry,
                RouteTestFixtures.noopRouteLineRepository(), RouteTestFixtures.noopBusRouteRepository(),
                RouteTestFixtures.noopCongestionRepository(),
                RouteTestFixtures.noopCongestionPredRepository());

        List<RouteSearchResponse> result = service.search("B", "C", null, null, null);

        RouteSearchResponse candidate = result.stream()
                .filter(r -> r.legs().size() == 1)
                .findFirst().orElseThrow();
        candidate.legs().forEach(leg -> assertEquals("unavailable", leg.geometryStatus()));
    }

    private List<Double> firstPoint(RouteLegResponse leg) {
        return leg.geometry().coordinates().get(0).get(0);
    }

    private List<Double> lastPoint(RouteLegResponse leg) {
        List<List<Double>> line = leg.geometry().coordinates().get(leg.geometry().coordinates().size() - 1);
        return line.get(line.size() - 1);
    }
}
