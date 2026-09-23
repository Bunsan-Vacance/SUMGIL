package com.ssafy.s15p21a104.domain.route.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anySet;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ssafy.s15p21a104.domain.bus.entity.BusRoute;
import com.ssafy.s15p21a104.domain.bus.repository.BusRouteRepository;
import com.ssafy.s15p21a104.domain.congestion.repository.CongestionRepository;
import com.ssafy.s15p21a104.domain.congestion.repository.CongestionPredRepository;
import com.ssafy.s15p21a104.domain.route.RouteTestFixtures;
import com.ssafy.s15p21a104.domain.route.bike.geometry.BikeGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.bus.geometry.BusGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.dto.response.MultiLineStringResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry;
import com.ssafy.s15p21a104.domain.route.geometry.RailGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.repository.RouteLineRepository;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class RouteSearchBusGeometryTest {

    @Mock
    private StationRepository stationRepository;
    @Mock
    private RouteGraphRegistry graphRegistry;
    @Mock
    private BusGeometryRegistry busGeometryRegistry;
    @Mock
    private BusRouteRepository busRouteRepository;

    @Test
    @DisplayName("BUS leg는 routeName을 붙인 뒤 버스 geometry를 조회한다")
    void dispatchesBusGeometryWithRouteAndStopNames() {
        Station from = RouteTestFixtures.mockStation("A", "출발 정류장");
        Station to = RouteTestFixtures.mockStation("C", "도착 정류장");
        lenient().when(stationRepository.findById("A")).thenReturn(Optional.of(from));
        lenient().when(stationRepository.findById("C")).thenReturn(Optional.of(to));
        RouteGraph graph = RouteTestFixtures.graphOf(new Edge("A", "C", "R1", 120, 0, TravelMode.BUS));
        when(graphRegistry.graph()).thenReturn(graph);
        lenient().when(graphRegistry.graphFor(
                org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.anyInt()))
                .thenReturn(graph);
        when(graphRegistry.stationInfos()).thenReturn(Map.of(
                "A", new RouteMapper.StationInfo("A", "출발 정류장", 37.5, 127.0),
                "C", new RouteMapper.StationInfo("C", "도착 정류장", 37.501, 127.001)));
        lenient().when(graphRegistry.transferTimes()).thenReturn(Map.of());
        lenient().when(graphRegistry.rentalIds()).thenReturn(java.util.Set.of());
        lenient().when(graphRegistry.bikeStock()).thenReturn(Map.of());

        BusRoute busRoute = mock(BusRoute.class);
        when(busRoute.getRouteId()).thenReturn("R1");
        when(busRoute.getName()).thenReturn("147");
        when(busRouteRepository.findAllById(anySet())).thenReturn(List.of(busRoute));

        MultiLineStringResponse geometry = MultiLineStringResponse.of(List.of(List.of(
                List.of(127.0, 37.5), List.of(127.001, 37.501))));
        when(busGeometryRegistry.geometryFor(
                eq("R1"), eq("A"), eq("C"), eq("147"), eq("출발 정류장"), eq("도착 정류장"),
                eq(37.5), eq(127.0), eq(37.501), eq(127.001)))
                .thenReturn(Optional.of(geometry));

        RouteSearchService service = new RouteSearchService(
                stationRepository, graphRegistry, new TransferRule(180),
                new RailGeometryRegistry(null, null), RouteTestFixtures.noopWalkGeometryRegistry(),
                RouteTestFixtures.noopBikeGeometryRegistry(), busGeometryRegistry,
                RouteTestFixtures.noopRouteLineRepository(), busRouteRepository,
                mock(CongestionRepository.class), mock(CongestionPredRepository.class));

        List<RouteSearchResponse> result = service.search("A", "C", null, null, null);

        assertEquals(1, result.size());
        assertEquals("147", result.get(0).legs().get(0).routeName());
        assertTrue(result.get(0).legs().get(0).geometry() != null);
        assertEquals("available", result.get(0).legs().get(0).geometryStatus());
        assertTrue(result.get(0).legs().get(0).distanceMeters() > 0);
        assertEquals(result.get(0).legs().get(0).distanceMeters(), result.get(0).totalDistanceMeters());
        verify(busGeometryRegistry).geometryFor(
                eq("R1"), eq("A"), eq("C"), eq("147"), eq("출발 정류장"), eq("도착 정류장"),
                eq(37.5), eq(127.0), eq(37.501), eq(127.001));
    }
}
