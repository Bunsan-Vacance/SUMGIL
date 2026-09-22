package com.ssafy.s15p21a104.domain.route.service;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bike;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;

import com.ssafy.s15p21a104.domain.congestion.entity.CongestionPred;
import com.ssafy.s15p21a104.domain.congestion.repository.CongestionPredRepository;
import com.ssafy.s15p21a104.domain.route.RouteTestFixtures;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry;
import com.ssafy.s15p21a104.domain.route.geometry.RailGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import java.math.BigDecimal;
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
 * S15P21A104-214 속도 3 + 혼잡 3 RED.
 * 배포 문서(route-mock-interface-213) 순서표와 일치해야 한다.
 */
@ExtendWith(MockitoExtension.class)
class SixRoutes214Test {

    @Mock
    private StationRepository stationRepository;

    @Mock
    private RouteGraphRegistry graphRegistry;

    @Mock
    private CongestionPredRepository congestionPredRepository;

    private RouteSearchService routeSearchService;

    @BeforeEach
    void setUp() {
        Map<String, Station> stations = new HashMap<>();
        for (String id : List.of("501", "502", "503", "504", "505", "R1")) {
            stations.put(id, RouteTestFixtures.mockStation(id, id + "역"));
        }
        for (Map.Entry<String, Station> entry : stations.entrySet()) {
            lenient().when(stationRepository.findById(entry.getKey()))
                    .thenReturn(Optional.of(entry.getValue()));
        }
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        for (String id : List.of("501", "502", "503", "504", "505", "R1")) {
            infos.put(id, new RouteMapper.StationInfo(id, id + "역", 37.5, 127.0));
        }
        lenient().when(graphRegistry.stationInfos()).thenReturn(infos);
        lenient().when(graphRegistry.rentalIds()).thenReturn(Set.of("R1"));
        lenient().when(graphRegistry.transferTimes()).thenReturn(Map.of());
        lenient().when(graphRegistry.bikeStock()).thenReturn(Map.of());
        // 6개 서로 다른 경로: 직통 4개 + 혼합 2개.
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("501", "503", "L1", 900),
                subway("501", "502", "L2", 200),
                subway("502", "503", "L2", 200),
                subway("501", "504", "L3", 300),
                subway("504", "503", "L3", 300),
                subway("501", "505", "L4", 250),
                subway("505", "503", "L4", 250),
                bike("501", "R1", 120),
                bike("R1", "503", 120),
                bike("502", "R1", 80)));
        lenient().when(graphRegistry.graphFor(
                org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.anyInt()))
                .thenAnswer(invocation -> graphRegistry.graph());
        // 158(통지 05 S-1): 링크 단위 조회로 대체 — lineId(routeId)로 구분한다.
        // 이 그래프의 링크는 전부 역번호 오름차순(501→50x)이라 방향은 항상 "상선".
        lenient().when(congestionPredRepository
                        .findById_PredDateAndId_FromStationIdAndId_ToStationIdAndId_LineIdAndId_DirectionAndId_TimeSlot(
                                any(), any(), any(), any(), any(), any()))
                .thenAnswer(invocation -> {
                    String lineId = invocation.getArgument(3);
                    // L1 가장 쾌적, L4·L3 중간, L2 혼잡.
                    BigDecimal level = switch (lineId) {
                        case "L1" -> BigDecimal.valueOf(1.0);
                        case "L4" -> BigDecimal.valueOf(3.0);
                        case "L3" -> BigDecimal.valueOf(5.0);
                        case "L2" -> BigDecimal.valueOf(9.0);
                        default -> null;
                    };
                    if (level == null) {
                        return Optional.empty();
                    }
                    return Optional.of(mockCongestionPred(level));
                });

        routeSearchService = new RouteSearchService(
                stationRepository, graphRegistry, new TransferRule(180),
                new RailGeometryRegistry(null, null), RouteTestFixtures.noopWalkGeometryRegistry(),
                RouteTestFixtures.noopBikeGeometryRegistry(),
                RouteTestFixtures.noopRouteLineRepository(), RouteTestFixtures.noopBusRouteRepository(),
                RouteTestFixtures.noopCongestionRepository(), congestionPredRepository);
    }

    @Test
    @DisplayName("214-T1: 속도 3 + 혼잡 3, 총 6개가 순서대로 나온다")
    void t1_속도3_혼잡3_6개() {
        List<RouteSearchResponse> result = routeSearchService.search("501", "503", null, null, null);

        assertEquals(6, result.size());
        // 속도 3: 시간순.
        assertEquals(RouteType.SHORTEST, result.get(0).routeType());
        assertEquals(RouteType.ALTERNATIVE, result.get(1).routeType());
        assertEquals(RouteType.ALTERNATIVE, result.get(2).routeType());
        assertTrue(result.get(0).totalMinutes() <= result.get(1).totalMinutes());
        assertTrue(result.get(1).totalMinutes() <= result.get(2).totalMinutes());
        // 혼잡 3: 쾌적순. 맨 앞은 LOW_CONGESTION.
        assertEquals(RouteType.LOW_CONGESTION, result.get(3).routeType());
        assertEquals(RouteType.ALTERNATIVE, result.get(4).routeType());
        assertEquals(RouteType.ALTERNATIVE, result.get(5).routeType());
    }

    @Test
    @DisplayName("214-T2: 후보 부족하면 있는 만큼만 나온다")
    void t2_후보부족_있는만큼() {
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("501", "503", "L1", 900)));

        List<RouteSearchResponse> result = routeSearchService.search("501", "503", null, null, null);

        assertTrue(result.size() >= 1);
        assertTrue(result.size() <= 6);
        assertEquals(RouteType.SHORTEST, result.get(0).routeType());
    }

    private CongestionPred mockCongestionPred(BigDecimal level) {
        CongestionPred pred = mock(CongestionPred.class);
        lenient().when(pred.getLevel()).thenReturn(level);
        return pred;
    }
}
