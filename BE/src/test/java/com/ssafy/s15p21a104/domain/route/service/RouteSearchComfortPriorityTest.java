package com.ssafy.s15p21a104.domain.route.service;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bike;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.ssafy.s15p21a104.domain.congestion.entity.CongestionPred;
import com.ssafy.s15p21a104.domain.congestion.repository.CongestionPredRepository;
import com.ssafy.s15p21a104.domain.route.RouteTestFixtures;
import com.ssafy.s15p21a104.domain.route.dto.request.RoutePriority;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
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
 * S15P21A104-157: priority=COMFORT일 때 혼잡도 낮은 후보가 우선 반환되는지 검증.
 *
 * <p>탐색 알고리즘·그래프는 그대로 두고, 이미 나온 후보를 재정렬만 하는지 확인한다.
 */
@ExtendWith(MockitoExtension.class)
class RouteSearchComfortPriorityTest {

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
        for (String id : List.of("501", "503", "R1")) {
            stations.put(id, RouteTestFixtures.mockStation(id, id + "역"));
        }
        for (Map.Entry<String, Station> entry : stations.entrySet()) {
            lenient().when(stationRepository.findById(entry.getKey()))
                    .thenReturn(Optional.of(entry.getValue()));
        }
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        infos.put("501", new RouteMapper.StationInfo("501", "에이역", 37.5, 127.0));
        infos.put("503", new RouteMapper.StationInfo("503", "씨역", 37.5, 127.0));
        infos.put("R1", new RouteMapper.StationInfo("R1", "대여소1", 37.5, 127.0));
        lenient().when(graphRegistry.stationInfos()).thenReturn(infos);
        lenient().when(graphRegistry.rentalIds()).thenReturn(Set.of("R1"));
        lenient().when(graphRegistry.transferTimes()).thenReturn(Map.of());
        lenient().when(graphRegistry.bikeStock()).thenReturn(Map.of());
        // 지하철(L1, 900초·15분, 느림) vs 자전거(A-R1-C, 240초·4분, 빠름).
        // 필터 없이 검색하면 시간순으로 자전거가 SHORTEST, 지하철이 ALTERNATIVE다.
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("501", "503", "L1", 900),
                bike("501", "R1", 120),
                bike("R1", "503", 120)));
        lenient().when(graphRegistry.graphFor(
                org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.anyInt()))
                .thenAnswer(invocation -> graphRegistry.graph());

        routeSearchService = new RouteSearchService(
                stationRepository, graphRegistry, new TransferRule(180),
                new RailGeometryRegistry(null, null), RouteTestFixtures.noopWalkGeometryRegistry(),
                RouteTestFixtures.noopBikeGeometryRegistry(),
                RouteTestFixtures.noopRouteLineRepository(), RouteTestFixtures.noopBusRouteRepository(),
                RouteTestFixtures.noopCongestionRepository(), congestionPredRepository);
    }

    @Test
    @DisplayName("priority=COMFORT면 혼잡도를 아는 후보가 혼잡 3 맨 앞에 LOW_CONGESTION으로 온다 (214: 속도 3 + 혼잡 3)")
    void COMFORT_혼잡도낮은후보_우선() {
        // 158: 링크 단위 조회로 대체 — lineId(routeId)로 구분한다.
        lenient().when(congestionPredRepository
                        .findById_PredDateAndId_FromStationIdAndId_ToStationIdAndId_LineIdAndId_DirectionAndId_TimeSlot(
                                any(), any(), any(), any(), any(), any()))
                .thenAnswer(invocation -> {
                    String lineId = invocation.getArgument(3);
                    if ("L1".equals(lineId)) {
                        return Optional.of(mockCongestionPred(BigDecimal.valueOf(20.0)));
                    }
                    return Optional.empty();
                });

        List<RouteSearchResponse> result = routeSearchService.search(
                "501", "503", null, RoutePriority.COMFORT, null);

        // 214 순서표: 0-2 속도, 3-5 혼잡. 혼잡 데이터 있는 SUBWAY 후보가 혼잡 3 맨 앞에 온다.
        // 이 그래프는 후보 2개라 six = 속도 2 + 혼잡 1 = 3개. LOW_CONGESTION은 2번이다.
        assertEquals(3, result.size());
        assertEquals(RouteType.SHORTEST, result.get(0).routeType());
        assertEquals(RouteType.LOW_CONGESTION, result.get(2).routeType());
        assertTrue(result.get(2).legs().stream().anyMatch(leg -> leg.mode() == TravelMode.SUBWAY));
    }

    @Test
    @DisplayName("혼잡도 데이터가 전혀 없으면 COMFORT를 요청해도 기존 순서·라벨을 그대로 둔다")
    void COMFORT_데이터없음_기존순서유지() {
        lenient().when(congestionPredRepository
                        .findById_PredDateAndId_FromStationIdAndId_ToStationIdAndId_LineIdAndId_DirectionAndId_TimeSlot(
                                any(), any(), any(), any(), any(), any()))
                .thenReturn(Optional.empty());

        List<RouteSearchResponse> withComfort = routeSearchService.search(
                "501", "503", null, RoutePriority.COMFORT, null);
        List<RouteSearchResponse> withoutPriority = routeSearchService.search(
                "501", "503", null, null, null);

        assertEquals(withoutPriority.get(0).routeType(), withComfort.get(0).routeType());
        assertEquals(withoutPriority.get(0).legs().size(), withComfort.get(0).legs().size());
    }

    @Test
    @DisplayName("priority 미지정(TIME)이면 기존 시간순 동작이 완전히 그대로다(회귀 없음)")
    void priority_미지정_기존동작_불변() {
        List<RouteSearchResponse> result = routeSearchService.search("501", "503", null, null, null);

        assertTrue(result.size() >= 2);
        assertEquals(RouteType.SHORTEST, result.get(0).routeType());
        assertTrue(result.get(0).legs().stream().allMatch(leg -> leg.mode() == TravelMode.BIKE));
    }

    private CongestionPred mockCongestionPred(BigDecimal level) {
        CongestionPred pred = mock(CongestionPred.class);
        lenient().when(pred.getLevel()).thenReturn(level);
        return pred;
    }
}
