package com.ssafy.s15p21a104.domain.route.service;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;

import com.ssafy.s15p21a104.domain.route.RouteTestFixtures;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry;
import com.ssafy.s15p21a104.domain.route.geometry.RailGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.loader.RouteEdgeRow;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.repository.RouteEdgeTimeRepository;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/**
 * S15P21A104-190 슬롯별 탐색 RED.
 * 출발 시각 슬롯에 맞는 그래프(소요시간)로 응답해야 한다.
 */
@ExtendWith(MockitoExtension.class)
class SlotSearch190Test {

    @Mock
    private StationRepository stationRepository;

    @Test
    @DisplayName("190-T4: 출발시각 다른 요청은 해당 슬롯 소요로 응답한다")
    void t4_슬롯별_다른소요() {
        stubStations();
        RouteEdgeTimeRepository edgeTimeRepository = mock(RouteEdgeTimeRepository.class);
        // default 슬롯(0,0): 100초. 평일 오전 슬롯(0,16): 500초.
        lenient().when(edgeTimeRepository.findSubwayEdgesBySlot(0, 0)).thenReturn(
                List.of(new RouteEdgeRow("A", "C", "L1", 100, 0)));
        lenient().when(edgeTimeRepository.findSubwayEdgesBySlot(0, 16)).thenReturn(
                List.of(new RouteEdgeRow("A", "C", "L1", 500, 0)));
        RouteGraphRegistry registry = registryWith(edgeTimeRepository,
                graphOf(subway("A", "C", "L1", 100)));

        RouteSearchService service = new RouteSearchService(
                stationRepository, registry, new TransferRule(180),
                new RailGeometryRegistry(null, null), RouteTestFixtures.noopWalkGeometryRegistry(),
                RouteTestFixtures.noopBikeGeometryRegistry(),
                RouteTestFixtures.noopRouteLineRepository(), RouteTestFixtures.noopBusRouteRepository(),
                RouteTestFixtures.noopCongestionRepository());

        // 평일 오전 8:10 → 슬롯(0,16) → 500초.
        List<RouteSearchResponse> peak = service.search(
                "A", "C", null, null, LocalDateTime.of(2026, 9, 8, 8, 10));
        // 슬롯(0,0) 시각 → 100초.
        List<RouteSearchResponse> early = service.search(
                "A", "C", null, null, LocalDateTime.of(2026, 9, 8, 0, 10));

        assertEquals(500 / 60.0, peak.get(0).totalMinutes(), 1e-9);
        assertEquals(100 / 60.0, early.get(0).totalMinutes(), 1e-9);
    }

    @Test
    @DisplayName("190-T5: 없는 슬롯은 default 폴백 (값 날조 없음)")
    void t5_없는슬롯_default폴백() {
        stubStations();
        RouteEdgeTimeRepository edgeTimeRepository = mock(RouteEdgeTimeRepository.class);
        lenient().when(edgeTimeRepository.findSubwayEdgesBySlot(0, 0)).thenReturn(
                List.of(new RouteEdgeRow("A", "C", "L1", 100, 0)));
        lenient().when(edgeTimeRepository.findSubwayEdgesBySlot(2, 20)).thenReturn(List.of());
        RouteGraphRegistry registry = registryWith(edgeTimeRepository,
                graphOf(subway("A", "C", "L1", 100)));

        RouteSearchService service = new RouteSearchService(
                stationRepository, registry, new TransferRule(180),
                new RailGeometryRegistry(null, null), RouteTestFixtures.noopWalkGeometryRegistry(),
                RouteTestFixtures.noopBikeGeometryRegistry(),
                RouteTestFixtures.noopRouteLineRepository(), RouteTestFixtures.noopBusRouteRepository(),
                RouteTestFixtures.noopCongestionRepository());

        // 일요일 오후 → 슬롯 행 없음 → default 100초.
        List<RouteSearchResponse> result = service.search(
                "A", "C", null, null, LocalDateTime.of(2026, 9, 13, 14, 0));

        assertEquals(100 / 60.0, result.get(0).totalMinutes(), 1e-9);
    }

    private void stubStations() {
        Station stationA = RouteTestFixtures.mockStation("A", "A역");
        Station stationC = RouteTestFixtures.mockStation("C", "C역");
        lenient().when(stationRepository.findById("A")).thenReturn(Optional.of(stationA));
        lenient().when(stationRepository.findById("C")).thenReturn(Optional.of(stationC));
    }

    private RouteGraphRegistry registryWith(
            RouteEdgeTimeRepository edgeTimeRepository,
            com.ssafy.s15p21a104.domain.route.graph.RouteGraph defaultGraph) {
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        infos.put("A", new RouteMapper.StationInfo("A", "에이역", 37.5, 127.0));
        infos.put("C", new RouteMapper.StationInfo("C", "씨역", 37.5, 127.0));
        Map<String, Station> stations = new HashMap<>();
        stations.put("A", RouteTestFixtures.mockStation("A", "A역"));
        stations.put("C", RouteTestFixtures.mockStation("C", "C역"));
        return new RouteGraphRegistry(edgeTimeRepository, stationRepository, null, null, null) {
            @Override
            public com.ssafy.s15p21a104.domain.route.graph.RouteGraph graph() {
                return defaultGraph;
            }

            @Override
            public Map<String, RouteMapper.StationInfo> stationInfos() {
                return infos;
            }

            @Override
            public java.util.Set<String> rentalIds() {
                return Set.of();
            }

            @Override
            public Map<TransferRule.TransferKey, Integer> transferTimes() {
                return Map.of();
            }

            @Override
            public Map<String, Integer> bikeStock() {
                return Map.of();
            }

            @Override
            public com.ssafy.s15p21a104.domain.route.graph.RouteGraph graphFor(int dow, int slot) {
                if (dow == 0 && slot == 0) {
                    return defaultGraph;
                }
                List<RouteEdgeRow> rows = edgeTimeRepository.findSubwayEdgesBySlot(dow, slot);
                if (rows == null || rows.isEmpty()) {
                    return defaultGraph;
                }
                RouteEdgeRow row = rows.get(0);
                return graphOf(subway(row.fromNode(), row.toNode(), row.routeId(), row.travelSec()));
            }
        };
    }
}
