package com.ssafy.s15p21a104.domain.route.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry;
import com.ssafy.s15p21a104.domain.route.geometry.RailGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import java.util.ArrayList;
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
 * 알고리즘 연동 경로 검증. 그래프·역 정보를 직접 조립해 주입하며 DB·Redis가 필요 없다.
 */
@ExtendWith(MockitoExtension.class)
class RouteSearchServiceWireTest {

    @Mock
    private StationRepository stationRepository;

    @Mock
    private RouteGraphRegistry graphRegistry;

    private RouteSearchService routeSearchService;

    @BeforeEach
    void setUp() {
        Station stationA = mockStation("A", "에이역");
        Station stationC = mockStation("C", "씨역");
        Station stationX = mockStation("X", "엑스역");
        lenient().when(stationRepository.findById("A")).thenReturn(Optional.of(stationA));
        lenient().when(stationRepository.findById("C")).thenReturn(Optional.of(stationC));
        lenient().when(stationRepository.findById("X")).thenReturn(Optional.of(stationX));
        RouteGraph graph = graphOf(
                new Edge("A", "B", "L1", 100, 0),
                new Edge("B", "C", "L2", 50, 0),
                // X는 고립 정점(A에서 도달 불가). 자기 루프로 정점만 등록한다.
                new Edge("X", "X", "L9", 10, 0));
        lenient().when(graphRegistry.graph()).thenReturn(graph);
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        infos.put("A", new RouteMapper.StationInfo("A", "에이역", 37.5, 127.0));
        infos.put("B", new RouteMapper.StationInfo("B", "비역", 37.5, 127.0));
        infos.put("C", new RouteMapper.StationInfo("C", "씨역", 37.5, 127.0));
        lenient().when(graphRegistry.stationInfos()).thenReturn(infos);
        routeSearchService = new RouteSearchService(
                stationRepository, graphRegistry, new TransferRule(180), new RailGeometryRegistry(null, null));
    }

    @Test
    @DisplayName("그래프가 있으면 알고리즘 경로(ALGORITHM)로 응답한다")
    void 그래프있으면_알고리즘응답() {
        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null);

        assertEquals(1, result.size());
        assertEquals(RouteType.SHORTEST, result.get(0).routeType());
        assertEquals(RouteSource.ALGORITHM, result.get(0).source());
        assertEquals((100 + 50 + 180) / 60.0, result.get(0).totalMinutes());
        assertEquals(2, result.get(0).legs().size());
    }

    @Test
    @DisplayName("연결 불가면 빈 배열로 응답한다(에러 아님)")
    void 연결불가_빈배열() {
        List<RouteSearchResponse> result = routeSearchService.search("A", "X", null, null);

        assertTrue(result.isEmpty());
    }

    private Station mockStation(String id, String name) {
        Station station = mock(Station.class);
        lenient().when(station.getStationId()).thenReturn(id);
        lenient().when(station.getName()).thenReturn(name);
        lenient().when(station.getLat()).thenReturn(37.5);
        lenient().when(station.getLng()).thenReturn(127.0);
        return station;
    }

    private static RouteGraph graphOf(Edge... edges) {
        Set<String> nodes = new HashSet<>();
        Map<String, List<Edge>> adjacency = new HashMap<>();
        Map<String, Set<String>> lines = new HashMap<>();
        for (Edge edge : edges) {
            nodes.add(edge.fromNode());
            nodes.add(edge.toNode());
            adjacency.computeIfAbsent(edge.fromNode(), key -> new ArrayList<>()).add(edge);
            lines.computeIfAbsent(edge.fromNode(), key -> new HashSet<>()).add(edge.routeId());
            lines.computeIfAbsent(edge.toNode(), key -> new HashSet<>()).add(edge.routeId());
        }
        return RouteGraph.of(nodes, adjacency, lines);
    }
}
