package com.ssafy.s15p21a104.domain.route.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry;
import com.ssafy.s15p21a104.domain.route.graph.Edge;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
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
 * 경로 검색 오류·미적재 계약 검증. 가짜 후보를 만들지 않으므로 mock 후보 테스트는 없다.
 * 알고리즘 정상계는 RouteSearchServiceWireTest가 담당한다.
 */
@ExtendWith(MockitoExtension.class)
class RouteSearchServiceTest {

    @Mock
    private StationRepository stationRepository;

    @Mock
    private RouteGraphRegistry graphRegistry;

    private RouteSearchService routeSearchService;

    @BeforeEach
    void setUp() {
        Station origin = mockStation("0222", "한티");
        Station dest = mockStation("0221", "역삼");
        lenient().when(stationRepository.findById("0222")).thenReturn(Optional.of(origin));
        lenient().when(stationRepository.findById("0221")).thenReturn(Optional.of(dest));
        lenient().when(stationRepository.findById("9999")).thenReturn(Optional.empty());
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                new Edge("0222", "0221", "2", 300, 0)));
        routeSearchService =
                new RouteSearchService(stationRepository, graphRegistry, new TransferRule(180));
    }

    @Test
    @DisplayName("출발지와 도착지가 같으면 SAME_ORIGIN_DEST")
    void 출발지와_도착지가_같으면_SAME_ORIGIN_DEST() {
        DomainException exception = assertThrows(DomainException.class,
                () -> routeSearchService.search("0222", "0222", null, null));

        assertEquals(ErrorType.SAME_ORIGIN_DEST, exception.getErrorType());
    }

    @Test
    @DisplayName("존재하지 않는 역이면 STATION_NOT_FOUND")
    void 존재하지_않는_역이면_STATION_NOT_FOUND() {
        DomainException exception = assertThrows(DomainException.class,
                () -> routeSearchService.search("9999", "0221", null, null));

        assertEquals(ErrorType.STATION_NOT_FOUND, exception.getErrorType());
    }

    @Test
    @DisplayName("그래프 미적재 시 빈 배열로 응답한다(가짜 후보 없음)")
    void 미적재시_빈배열() {
        RouteSearchService unloaded =
                new RouteSearchService(stationRepository, null, new TransferRule(180));

        List<RouteSearchResponse> result = unloaded.search("0222", "0221", null, null);

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
