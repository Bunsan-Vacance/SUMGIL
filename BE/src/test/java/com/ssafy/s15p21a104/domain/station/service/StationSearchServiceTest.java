package com.ssafy.s15p21a104.domain.station.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

import com.ssafy.s15p21a104.domain.route.repository.RouteEdgeTimeRepository;
import com.ssafy.s15p21a104.domain.route.repository.RouteLineRepository;
import com.ssafy.s15p21a104.domain.route.repository.StationRouteEdge;
import com.ssafy.s15p21a104.domain.station.dto.response.StationSearchResultResponse;
import com.ssafy.s15p21a104.domain.station.entity.Line;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class StationSearchServiceTest {

    @Mock
    private StationRepository stationRepository;

    @Mock
    private RouteEdgeTimeRepository routeEdgeTimeRepository;

    @Mock
    private RouteLineRepository routeLineRepository;

    private StationSearchService stationSearchService;

    @BeforeEach
    void setUp() {
        stationSearchService = new StationSearchService(stationRepository, routeEdgeTimeRepository, routeLineRepository);
    }

    @Test
    @DisplayName("정확 일치가 접두·부분 일치보다 먼저 온다")
    void 정확일치_우선() {
        Station gangnam = mockStation("222", "강남", 37.4979, 127.0276);
        Station gangnamgucheong = mockStation("2201", "강남구청", 37.5175, 127.0473);
        lenient().when(stationRepository.findByNameContainingIgnoreCase("강남"))
                .thenReturn(List.of(gangnamgucheong, gangnam));
        lenient().when(routeEdgeTimeRepository.findSubwayRouteEdgesTouchingStations(any()))
                .thenReturn(List.of(
                        new StationRouteEdge("222", "223", "1002"),
                        new StationRouteEdge("2201", "2202", "1007")));
        Line line1002 = mockLine("1002", "2호선");
        Line line1007 = mockLine("1007", "7호선");
        lenient().when(routeLineRepository.findAllById(any())).thenReturn(List.of(line1002, line1007));

        List<StationSearchResultResponse> result = stationSearchService.search("강남");

        assertEquals(2, result.size());
        assertEquals("222", result.get(0).stationId());
        assertEquals("2호선", result.get(0).lineName());
        assertEquals("2201", result.get(1).stationId());
    }

    @Test
    @DisplayName("끝의 '역' 표기를 허용한다")
    void 역_표기_허용() {
        Station gangbyeon = mockStation("214", "강변", 37.5352, 127.0947);
        lenient().when(stationRepository.findByNameContainingIgnoreCase("강변")).thenReturn(List.of(gangbyeon));
        lenient().when(routeEdgeTimeRepository.findSubwayRouteEdgesTouchingStations(any()))
                .thenReturn(List.of(new StationRouteEdge("214", "215", "1002")));
        Line line1002 = mockLine("1002", "2호선");
        lenient().when(routeLineRepository.findAllById(any())).thenReturn(List.of(line1002));

        List<StationSearchResultResponse> result = stationSearchService.search("강변역");

        assertEquals(1, result.size());
        assertEquals("214", result.get(0).stationId());
    }

    @Test
    @DisplayName("환승역은 노선 수만큼 행이 나뉜다")
    void 환승역_노선별_행분리() {
        Station wangsimni = mockStation("1023", "왕십리", 37.5613, 127.0374);
        lenient().when(stationRepository.findByNameContainingIgnoreCase("왕십리")).thenReturn(List.of(wangsimni));
        lenient().when(routeEdgeTimeRepository.findSubwayRouteEdgesTouchingStations(any()))
                .thenReturn(List.of(
                        new StationRouteEdge("1022", "1023", "1002"),
                        new StationRouteEdge("1023", "1024", "1005")));
        Line line1002 = mockLine("1002", "2호선");
        Line line1005 = mockLine("1005", "5호선");
        lenient().when(routeLineRepository.findAllById(any())).thenReturn(List.of(line1002, line1005));

        List<StationSearchResultResponse> result = stationSearchService.search("왕십리");

        assertEquals(2, result.size());
        assertTrue(result.stream().allMatch(row -> row.stationId().equals("1023")));
        assertEquals(List.of("1002", "1005"), result.stream().map(StationSearchResultResponse::lineId).sorted().toList());
    }

    @Test
    @DisplayName("빈 검색어는 에러 없이 빈 목록")
    void 빈검색어_빈목록() {
        List<StationSearchResultResponse> result = stationSearchService.search("   ");

        assertTrue(result.isEmpty());
    }

    @Test
    @DisplayName("매칭된 역이 없으면 노선 조회를 하지 않는다")
    void 매칭없으면_노선조회_생략() {
        lenient().when(stationRepository.findByNameContainingIgnoreCase("존재안함")).thenReturn(List.of());

        List<StationSearchResultResponse> result = stationSearchService.search("존재안함");

        assertTrue(result.isEmpty());
        verify(routeEdgeTimeRepository, never()).findSubwayRouteEdgesTouchingStations(any());
    }

    private Station mockStation(String id, String name, double lat, double lng) {
        Station station = mock(Station.class);
        lenient().when(station.getStationId()).thenReturn(id);
        lenient().when(station.getName()).thenReturn(name);
        lenient().when(station.getLat()).thenReturn(lat);
        lenient().when(station.getLng()).thenReturn(lng);
        return station;
    }

    private Line mockLine(String id, String name) {
        Line line = mock(Line.class);
        lenient().when(line.getLineId()).thenReturn(id);
        lenient().when(line.getName()).thenReturn(name);
        return line;
    }
}
