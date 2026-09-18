package com.ssafy.s15p21a104.domain.route.service;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.walk;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.lenient;

import com.ssafy.s15p21a104.domain.route.RouteTestFixtures;
import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder;
import com.ssafy.s15p21a104.domain.route.bus.BusEdgeBuilder.RouteStop;
import com.ssafy.s15p21a104.domain.route.bus.BusRouteIndex;
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
import java.util.HashSet;
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
 * S15P21A104-234 재현 검증. 정규 그래프 + 실제 인덱스를 통과하면
 * 같은 구간 버스 중복이 슬롯을 독식하지 않고 옵션으로 붙는다.
 */
@ExtendWith(MockitoExtension.class)
class BusCorridorService234Test {

    private static Map<String, List<RouteStop>> busRoutes() {
        return Map.of(
                "108", List.of(
                        new RouteStop("S1", 1, 37.5000, 127.0000),
                        new RouteStop("S2", 2, 37.5000, 127.0050)),
                "143", List.of(
                        new RouteStop("S1", 1, 37.5000, 127.0000),
                        new RouteStop("S2", 2, 37.5000, 127.0050)));
    }

    @Mock
    private StationRepository stationRepository;

    @Mock
    private RouteGraphRegistry graphRegistry;

    private RouteSearchService routeSearchService;

    @BeforeEach
    void setUp() {
        Station stationA = RouteTestFixtures.mockStation("A", "A역");
        Station stationC = RouteTestFixtures.mockStation("C", "C역");
        lenient().when(stationRepository.findById("A")).thenReturn(Optional.of(stationA));
        lenient().when(stationRepository.findById("C")).thenReturn(Optional.of(stationC));
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        infos.put("A", new RouteMapper.StationInfo("A", "A역", 37.5, 127.0));
        infos.put("S1", new RouteMapper.StationInfo("S1", "정류장1", 37.5, 127.0));
        infos.put("S2", new RouteMapper.StationInfo("S2", "정류장2", 37.5, 127.01));
        infos.put("B", new RouteMapper.StationInfo("B", "B역", 37.5, 127.0));
        infos.put("C", new RouteMapper.StationInfo("C", "C역", 37.5, 127.0));
        lenient().when(graphRegistry.stationInfos()).thenReturn(infos);
        lenient().when(graphRegistry.rentalIds()).thenReturn(Set.of());
        lenient().when(graphRegistry.transferTimes()).thenReturn(Map.of());
        lenient().when(graphRegistry.bikeStock()).thenReturn(Map.of());
        List<com.ssafy.s15p21a104.domain.route.graph.Edge> edges = new java.util.ArrayList<>();
        edges.add(subway("A", "C", "L1", 1500));
        edges.add(walk("A", "S1", 120));
        edges.addAll(BusEdgeBuilder.buildCorridors(busRoutes()));
        edges.add(walk("S2", "C", 120));
        edges.add(subway("A", "B", "L2", 200));
        edges.add(subway("B", "C", "L3", 200));
        lenient().when(graphRegistry.graph())
                .thenReturn(graphOf(edges.toArray(new com.ssafy.s15p21a104.domain.route.graph.Edge[0])));
        lenient().when(graphRegistry.graphFor(
                        org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.anyInt()))
                .thenAnswer(invocation -> graphRegistry.graph());
        lenient().when(graphRegistry.busRouteIndex())
                .thenReturn(BusRouteIndex.build(busRoutes()));
        routeSearchService = new RouteSearchService(
                stationRepository, graphRegistry, new TransferRule(180),
                new RailGeometryRegistry(null, null), RouteTestFixtures.noopWalkGeometryRegistry(),
                RouteTestFixtures.noopBikeGeometryRegistry(),
                RouteTestFixtures.noopRouteLineRepository(), RouteTestFixtures.noopBusRouteRepository(),
                RouteTestFixtures.noopCongestionRepository());
    }

    private static String corridorOf(RouteSearchResponse response) {
        StringBuilder signature = new StringBuilder();
        for (RouteLegResponse leg : response.legs()) {
            signature.append(leg.mode()).append(':')
                    .append(leg.fromNodeId()).append("->").append(leg.toNodeId()).append(':')
                    .append(leg.routeId()).append('|');
        }
        return signature.toString();
    }

    @Test
    @DisplayName("234-T50: 같은 구간 버스 중복이 후보를 독식하지 않는다")
    void t50_중복해소() {
        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null, null);

        assertTrue(result.size() >= 1);
        Set<String> seen = new HashSet<>();
        for (RouteSearchResponse response : result) {
            assertTrue(seen.add(corridorOf(response)),
                    "물리 중복 후보 검출: " + corridorOf(response));
        }
        // routeId 무시 corridor 유일성: 정규 구간이라 노선 선택이 미뤄지므로
        // 노선을 뺀 물리 서명이 겹치면 같은 경로의 중복이다.
        Set<String> seenPhysical = new HashSet<>();
        for (RouteSearchResponse response : result) {
            StringBuilder physical = new StringBuilder();
            for (RouteLegResponse leg : response.legs()) {
                physical.append(leg.mode()).append(':')
                        .append(leg.fromNodeId()).append("->").append(leg.toNodeId()).append('|');
            }
            assertTrue(seenPhysical.add(physical.toString()),
                    "물리 중복 후보 검출(routeId 무시): " + physical);
        }
        for (RouteSearchResponse response : result) {
            double sum = response.legs().stream().mapToDouble(RouteLegResponse::minutes).sum();
            assertEquals(response.totalMinutes(), sum, 1e-9);
        }
    }

    @Test
    @DisplayName("234-T51: BUS leg에 실제 노선 목록이 옵션으로 붙는다")
    void t51_옵션부착() {
        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null, null);

        boolean found = false;
        for (RouteSearchResponse response : result) {
            for (RouteLegResponse leg : response.legs()) {
                if (leg.mode() == TravelMode.BUS) {
                    found = true;
                    assertTrue(leg.routeOptions() != null && leg.routeOptions().size() == 2,
                            "옵션 2건(108·143)이어야 한다");
                    Set<String> ids = new HashSet<>();
                    leg.routeOptions().forEach(option -> ids.add(option.routeId()));
                    assertEquals(Set.of("108", "143"), ids);
                }
            }
        }
        assertTrue(found, "BUS leg가 응답에 있어야 한다");
    }
}
