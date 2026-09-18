package com.ssafy.s15p21a104.domain.route.service;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;

import com.ssafy.s15p21a104.domain.route.RouteTestFixtures;
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
                new Edge("A", "B", "L1", 100, 0, TravelMode.SUBWAY),
                new Edge("B", "C", "L2", 50, 0, TravelMode.SUBWAY),
                // X는 고립 정점(A에서 도달 불가). 자기 루프로 정점만 등록한다.
                new Edge("X", "X", "L9", 10, 0, TravelMode.SUBWAY));
        lenient().when(graphRegistry.graph()).thenReturn(graph);
        lenient().when(graphRegistry.graphFor(
                org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.anyInt()))
                .thenAnswer(invocation -> graphRegistry.graph());
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        infos.put("A", new RouteMapper.StationInfo("A", "에이역", 37.5, 127.0));
        infos.put("B", new RouteMapper.StationInfo("B", "비역", 37.5, 127.0));
        infos.put("C", new RouteMapper.StationInfo("C", "씨역", 37.5, 127.0));
        lenient().when(graphRegistry.stationInfos()).thenReturn(infos);
        lenient().when(graphRegistry.transferTimes()).thenReturn(Map.of(
                new TransferRule.TransferKey("B", "L1", "L2"), 60));
        routeSearchService = new RouteSearchService(
                stationRepository, graphRegistry, new TransferRule(180), new RailGeometryRegistry(null, null),
                RouteTestFixtures.noopWalkGeometryRegistry(), RouteTestFixtures.noopBikeGeometryRegistry(),
                RouteTestFixtures.noopRouteLineRepository(), RouteTestFixtures.noopBusRouteRepository(),
                RouteTestFixtures.noopCongestionRepository(),
                RouteTestFixtures.noopCongestionPredRepository());
    }

    @Test
    @DisplayName("106-T1: TRANSFER leg에 실측 환승 시간이 들어간다")
    void t106_TRANSFER_leg_실측값() {
        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null, null);

        assertEquals(1, result.size());
        assertEquals(RouteType.SHORTEST, result.get(0).routeType());
        assertEquals(RouteSource.ALGORITHM, result.get(0).source());
        assertEquals((100 + 50 + 60) / 60.0, result.get(0).totalMinutes());
        assertEquals(3, result.get(0).legs().size());
        assertEquals(TravelMode.SUBWAY, result.get(0).legs().get(0).mode());
        assertEquals(TravelMode.TRANSFER, result.get(0).legs().get(1).mode());
        assertEquals(TravelMode.SUBWAY, result.get(0).legs().get(2).mode());
        assertEquals(60 / 60.0, result.get(0).legs().get(1).minutes(), 1e-9);
    }

    @Test
    @DisplayName("연결 불가면 빈 배열로 응답한다(에러 아님)")
    void 연결불가_빈배열() {
        List<RouteSearchResponse> result = routeSearchService.search("A", "X", null, null, null);

        assertTrue(result.isEmpty());
    }

    @Test
    @DisplayName("역 좌표가 없어도(위경도 null) geometry 부착 단계에서 500 없이 응답한다")
    void 역좌표_null이어도_예외없음() {
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        infos.put("A", new RouteMapper.StationInfo("A", "에이역", 37.5, 127.0));
        infos.put("B", new RouteMapper.StationInfo("B", "비역", null, null));
        infos.put("C", new RouteMapper.StationInfo("C", "씨역", 37.5, 127.0));
        lenient().when(graphRegistry.stationInfos()).thenReturn(infos);

        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null, null);

        assertEquals(1, result.size());
        result.get(0).legs().forEach(leg -> assertEquals("unavailable", leg.geometryStatus()));
    }

    @Test
    @DisplayName("109-T8: 자전거 지름길이 이기면 BIKE leg로 응답한다")
    void t109_자전거지름길_BIKEleg() {
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                new Edge("A", "C", "L1", 900, 0, TravelMode.SUBWAY),
                new Edge("A", "R1", "BIKE", 120, 0, TravelMode.BIKE),
                new Edge("R1", "C", "BIKE", 120, 0, TravelMode.BIKE)));
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        infos.put("A", new RouteMapper.StationInfo("A", "에이역", 37.5, 127.0));
        infos.put("R1", new RouteMapper.StationInfo("R1", "대여소", 37.5, 127.0));
        infos.put("C", new RouteMapper.StationInfo("C", "씨역", 37.5, 127.0));
        lenient().when(graphRegistry.stationInfos()).thenReturn(infos);

        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null, null);

        // 185: SUBWAY 전용 조합으로도 (더 느린) 대체 후보가 따로 나온다.
        assertTrue(result.size() >= 1);
        assertEquals(1, result.get(0).legs().size());
        assertEquals(TravelMode.BIKE, result.get(0).legs().get(0).mode());
        assertEquals((120 + 120) / 60.0, result.get(0).totalMinutes());
    }

    private Station mockStation(String id, String name) {
        return com.ssafy.s15p21a104.domain.route.RouteTestFixtures.mockStation(id, name);
    }
}
