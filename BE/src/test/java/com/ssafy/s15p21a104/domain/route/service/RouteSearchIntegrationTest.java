package com.ssafy.s15p21a104.domain.route.service;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bike;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.bus;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.walk;
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
 * 탐색 파이프라인 통합 테스트: finder → mapper → service → geometry → stockGate를
 * 서비스 진입점(search)으로 관통한다. DB·Redis 없이 fixture 그래프로 수행한다.
 *
 * <p>역전 = 지하철만 가는 최단경로보다 중간에 따릉이로 갈아타는 게 더 빠른 구간
 * (route-api-spec.md 배경). 케이스를 만들어 검증한다.
 */
@ExtendWith(MockitoExtension.class)
class RouteSearchIntegrationTest {

    @Mock
    private StationRepository stationRepository;

    @Mock
    private RouteGraphRegistry graphRegistry;

    private RouteSearchService routeSearchService;

    @BeforeEach
    void setUp() {
        Map<String, Station> stations = new HashMap<>();
        for (String id : List.of("A", "B", "C", "R1", "R2", "R3", "X")) {
            stations.put(id, mockStation(id, id + "역"));
        }
        for (Map.Entry<String, Station> entry : stations.entrySet()) {
            lenient().when(stationRepository.findById(entry.getKey()))
                    .thenReturn(Optional.of(entry.getValue()));
        }
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        infos.put("A", new RouteMapper.StationInfo("A", "에이역", 37.5, 127.0));
        infos.put("B", new RouteMapper.StationInfo("B", "비역", 37.5, 127.0));
        infos.put("C", new RouteMapper.StationInfo("C", "씨역", 37.5, 127.0));
        infos.put("R1", new RouteMapper.StationInfo("R1", "대여소1", 37.5, 127.0));
        infos.put("R2", new RouteMapper.StationInfo("R2", "대여소2", 37.5, 127.0));
        infos.put("R3", new RouteMapper.StationInfo("R3", "대여소3", 37.5, 127.0));
        lenient().when(graphRegistry.stationInfos()).thenReturn(infos);
        lenient().when(graphRegistry.rentalIds()).thenReturn(Set.of("R1", "R2", "R3"));
        lenient().when(graphRegistry.transferTimes()).thenReturn(Map.of(
                new TransferRule.TransferKey("B", "L1", "L2"), 60));
        lenient().when(graphRegistry.bikeStock()).thenReturn(Map.of());
        // 기본 그래프: A→B→C 지하철. 개별 케이스가 교체한다.
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("A", "B", "L1", 100),
                subway("B", "C", "L1", 100)));
        // 개별 테스트가 graphRegistry.graph()를 다른 그래프로 재스텁해도 그때그때 다시 계산되도록
        // thenAnswer로 지연 평가한다(S15P21A104-155, 13개 테스트가 각자 다른 그래프를 씀).
        routeSearchService = new RouteSearchService(
                stationRepository, graphRegistry, new TransferRule(180),
                new RailGeometryRegistry(null, null), RouteTestFixtures.noopWalkGeometryRegistry(),
                RouteTestFixtures.noopBikeGeometryRegistry(),
                RouteTestFixtures.noopRouteLineRepository(), RouteTestFixtures.noopBusRouteRepository(),
                RouteTestFixtures.noopCongestionRepository());
    }

    @Test
    @DisplayName("IT1: 지하철만 있으면 SUBWAY 단일 응답이다")
    void it1_지하철만_SUBWAY() {
        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null, null);

        assertEquals(1, result.size());
        assertEquals(RouteType.SHORTEST, result.get(0).routeType());
        assertEquals(RouteSource.ALGORITHM, result.get(0).source());
        assertEquals((100 + 100) / 60.0, result.get(0).totalMinutes(), 1e-9);
        assertEquals(1, result.get(0).legs().size());
        assertEquals(TravelMode.SUBWAY, result.get(0).legs().get(0).mode());
    }

    @Test
    @DisplayName("IT2: 역전 — 따릉이 지름길이 이기면 BIKE legs로 응답한다 (대여소 경계 분할)")
    void it2_역전_따릉이우위() {
        // 지하철 A→C 직통 900초 vs 따릉이 A→R1→C 240초. 자전거가 이겨야 한다.
        // 122 경계 분할로 대여소 양단이 보인다.
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("A", "C", "L1", 900),
                bike("A", "R1", 120),
                bike("R1", "C", 120)));

        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null, null);

        // 185: SUBWAY 전용 조합으로도 (더 느린) 대체 후보가 따로 나온다 — 최소 1개, 가장 빠른 건 BIKE.
        assertTrue(result.size() >= 1);
        assertEquals(RouteType.SHORTEST, result.get(0).routeType());
        assertEquals(2, result.get(0).legs().size());
        assertTrue(result.get(0).legs().stream().allMatch(leg -> leg.mode() == TravelMode.BIKE));
        assertEquals("A", result.get(0).legs().get(0).fromNodeId());
        assertEquals("R1", result.get(0).legs().get(0).toNodeId());
        assertEquals("R1", result.get(0).legs().get(1).fromNodeId());
        assertEquals("C", result.get(0).legs().get(1).toNodeId());
        assertEquals((120 + 120) / 60.0, result.get(0).totalMinutes(), 1e-9);
    }

    @Test
    @DisplayName("IT3: 역전 — 혼합(지하철+따릉이) 경로가 응답된다")
    void it3_역전_혼합경로() {
        // A→B 지하철 100초, B→R1→C 따릉이 240초 vs A→B→C 지하철 500초.
        // 혼합(A→B 지하철, B→R1→C 따릉이)이 전체 340초+환승으로 이긴다.
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("A", "B", "L1", 100),
                subway("B", "C", "L2", 400),
                bike("B", "R1", 120),
                bike("R1", "C", 120)));

        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null, null);

        assertTrue(result.size() >= 1);
        List<TravelMode> modes = result.get(0).legs().stream().map(leg -> leg.mode()).toList();
        assertTrue(modes.contains(TravelMode.BIKE));
        assertTrue(modes.contains(TravelMode.SUBWAY));
    }

    @Test
    @DisplayName("IT4: 모드 필터 — BIKE만 허용하면 자전거 후보만 남는다(185: 이제 후보를 실제로 만든다)")
    void it4_모드필터_BIKE만_필터() {
        // 지하철 직통 300초가 더 빠르지만, BIKE 필터를 걸면 자전거 후보(800초)만 응답에 남아야 한다.
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("A", "C", "L1", 300),
                bike("A", "R1", 400),
                bike("R1", "C", 400)));

        List<RouteSearchResponse> result =
                routeSearchService.search("A", "C", List.of(TravelMode.BIKE), null, null);

        assertEquals(1, result.size());
        assertTrue(result.get(0).legs().stream().allMatch(leg -> leg.mode() == TravelMode.BIKE));
        assertEquals((400 + 400) / 60.0, result.get(0).totalMinutes(), 1e-9);
    }

    @Test
    @DisplayName("IT5: TRANSFER leg에 실측 환승 시간이 들어간다")
    void it5_환승실측_TRANSFER() {
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("A", "B", "L1", 100),
                subway("B", "C", "L2", 50)));

        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null, null);

        assertEquals(1, result.size());
        assertEquals(3, result.get(0).legs().size());
        assertEquals(TravelMode.TRANSFER, result.get(0).legs().get(1).mode());
        assertEquals(60 / 60.0, result.get(0).legs().get(1).minutes(), 1e-9);
        assertEquals((100 + 50 + 60) / 60.0, result.get(0).totalMinutes(), 1e-9);
    }

    @Test
    @DisplayName("IT6: 재고 소진 대여소를 경유하는 후보만 제외된다(다른 후보는 남는다, 185)")
    void it6_재고소진_제외() {
        // 자전거 후보(240초)는 R1 재고 소진으로 걸러지지만, SUBWAY 전용 후보(900초)는 R1을
        // 거치지 않으므로 그대로 응답에 남아야 한다 — 재고 게이트는 후보 하나만 걸러야 한다.
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("A", "C", "L1", 900),
                bike("A", "R1", 120),
                bike("R1", "C", 120)));
        lenient().when(graphRegistry.bikeStock()).thenReturn(Map.of("R1", 0));

        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null, null);

        assertEquals(1, result.size());
        assertTrue(result.get(0).legs().stream().noneMatch(leg -> leg.mode() == TravelMode.BIKE));
        assertEquals(900 / 60.0, result.get(0).totalMinutes(), 1e-9);
    }

    @Test
    @DisplayName("IT7: 연결 불가면 빈 배열이다(에러 아님)")
    void it7_연결불가_빈배열() {
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("A", "B", "L1", 100),
                subway("C", "C", "L9", 10)));

        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null, null);

        assertTrue(result.isEmpty());
    }

    @Test
    @DisplayName("IT8: 도보 지름길이 이기면 WALK legs로 응답한다 (213 T2: K-path라 대체 후보도 나온다)")
    void it8_도보우위_WALK() {
        // 지하철 A→C 직통 900초 vs 도보 A→R1→C 240초. 도보가 첫 후보, 지하철이 대체 후보.
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("A", "C", "L1", 900),
                walk("A", "R1", 120),
                walk("R1", "C", 120)));

        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null, null);

        assertEquals(2, result.size());
        assertEquals(2, result.get(0).legs().size());
        assertTrue(result.get(0).legs().stream().allMatch(leg -> leg.mode() == TravelMode.WALK));
        assertEquals("A", result.get(0).legs().get(0).fromNodeId());
        assertEquals("R1", result.get(0).legs().get(0).toNodeId());
        assertEquals("R1", result.get(0).legs().get(1).fromNodeId());
        assertEquals("C", result.get(0).legs().get(1).toNodeId());
        assertEquals((120 + 120) / 60.0, result.get(0).totalMinutes(), 1e-9);
    }

    @Test
    @DisplayName("IT9: 혼합(지하철+도보) 경로가 응답된다 (213 T2: K-path라 대체 후보도 나온다)")
    void it9_혼합_지하철도보() {
        // A→B 지하철 100초, B→R1→C 도보 240초 vs A→B→C 지하철 500초(환승 포함).
        // 혼합이 첫 후보, 지하철 직통이 대체 후보.
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("A", "B", "L1", 100),
                subway("B", "C", "L2", 400),
                walk("B", "R1", 120),
                walk("R1", "C", 120)));

        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null, null);

        assertEquals(2, result.size());
        List<TravelMode> modes = result.get(0).legs().stream().map(leg -> leg.mode()).toList();
        assertTrue(modes.contains(TravelMode.WALK));
        assertTrue(modes.contains(TravelMode.SUBWAY));
    }

    @Test
    @DisplayName("IT10: 122 접근 WALK+본선 BIKE 혼합에 대여소가 보인다 (213 T1: 접근 TRANSFER 없음)")
    void it10_122_접근WALK_본선BIKE() {
        // 지하철 A→C 직통 900초 vs 도보 A→R1 + 자전거 R1→R2 + 도보 R2→C 360초.
        // 혼합(360초)이 이기고 대여소 양단이 보인다. 접근 경계는 TRANSFER가 아니다.
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("A", "C", "L1", 900),
                walk("A", "R1", 120),
                bike("R1", "R2", 120),
                walk("R2", "C", 120)));

        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null, null);

        assertTrue(result.size() >= 1);
        assertEquals(3, result.get(0).legs().size());
        assertEquals(TravelMode.WALK, result.get(0).legs().get(0).mode());
        assertEquals(TravelMode.BIKE, result.get(0).legs().get(1).mode());
        assertEquals(TravelMode.WALK, result.get(0).legs().get(2).mode());
        assertEquals("A", result.get(0).legs().get(0).fromNodeId());
        assertEquals("R1", result.get(0).legs().get(0).toNodeId());
        assertEquals("R1", result.get(0).legs().get(1).fromNodeId());
        assertEquals("R2", result.get(0).legs().get(1).toNodeId());
        assertEquals("R2", result.get(0).legs().get(2).fromNodeId());
        assertEquals("C", result.get(0).legs().get(2).toNodeId());
    }

    @Test
    @DisplayName("IT11: 122 복수 hop 본선도 중간 대여소가 보인다 (213 T1: 접근 TRANSFER 없음)")
    void it11_122_본선복수hop_가시성() {
        // 지하철 A→C 직통 1500초 vs 도보+자전거2hop+도보 440초.
        // 혼합(440초)이 이기고 중간 대여소 R2가 보인다.
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("A", "C", "L1", 1500),
                walk("A", "R1", 120),
                bike("R1", "R2", 100),
                bike("R2", "R3", 100),
                walk("R3", "C", 120)));

        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null, null);

        assertTrue(result.size() >= 1);
        assertEquals(4, result.get(0).legs().size());
        assertEquals(TravelMode.BIKE, result.get(0).legs().get(1).mode());
        assertEquals(TravelMode.BIKE, result.get(0).legs().get(2).mode());
        assertEquals("R1", result.get(0).legs().get(1).fromNodeId());
        assertEquals("R2", result.get(0).legs().get(1).toNodeId());
        assertEquals("R2", result.get(0).legs().get(2).fromNodeId());
        assertEquals("R3", result.get(0).legs().get(2).toNodeId());
    }

    @Test
    @DisplayName("IT12: 버스 지름길이 이기면 BUS leg로 응답한다")
    void it12_버스우위_BUS() {
        // 지하철 A→C 직통 900초 vs 버스 A→T1→C 240초. 버스가 이겨야 한다.
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("A", "C", "L1", 900),
                bus("A", "T1", "B100", 120),
                bus("T1", "C", "B100", 120)));

        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null, null);

        // 185: BUS(240초, 최단)와 SUBWAY 전용(900초, 대체) 딱 2개 후보로 정확히 갈린다 — 중복 없음.
        assertEquals(2, result.size());
        assertEquals(RouteType.SHORTEST, result.get(0).routeType());
        assertEquals(1, result.get(0).legs().size());
        assertEquals(TravelMode.BUS, result.get(0).legs().get(0).mode());
        assertEquals((120 + 120) / 60.0, result.get(0).totalMinutes(), 1e-9);
        assertEquals(RouteType.ALTERNATIVE, result.get(1).routeType());
        assertEquals(TravelMode.SUBWAY, result.get(1).legs().get(0).mode());
        assertEquals(900 / 60.0, result.get(1).totalMinutes(), 1e-9);
    }

    @Test
    @DisplayName("IT12b: 모드 필터 조합 — 허용 조합에 맞는 후보만 남는다(185)")
    void it12b_모드필터_조합() {
        // 지하철 900초 vs 버스 240초. modes=[SUBWAY,BUS]면 둘 다, modes=[BUS]면 버스만 남아야 한다.
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("A", "C", "L1", 900),
                bus("A", "T1", "B100", 120),
                bus("T1", "C", "B100", 120)));

        List<RouteSearchResponse> both = routeSearchService.search(
                "A", "C", List.of(TravelMode.SUBWAY, TravelMode.BUS), null, null);
        assertEquals(2, both.size());

        List<RouteSearchResponse> busOnly = routeSearchService.search(
                "A", "C", List.of(TravelMode.BUS), null, null);
        assertEquals(1, busOnly.size());
        assertEquals(TravelMode.BUS, busOnly.get(0).legs().get(0).mode());

        List<RouteSearchResponse> bikeOnly = routeSearchService.search(
                "A", "C", List.of(TravelMode.BIKE), null, null);
        assertTrue(bikeOnly.isEmpty());
    }

    @Test
    @DisplayName("IT12c: 필터로 SHORTEST가 빠지면 남은 첫 후보가 SHORTEST로 재라벨링된다(FE-175 지적)")
    void it12c_필터후_재라벨링() {
        // 버스(240초)가 원래 SHORTEST, 지하철(900초)이 ALTERNATIVE. SUBWAY만 필터하면
        // 지하철 혼자 남는데, 이때도 routeType은 ALTERNATIVE가 아니라 SHORTEST여야 한다.
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("A", "C", "L1", 900),
                bus("A", "T1", "B100", 120),
                bus("T1", "C", "B100", 120)));

        List<RouteSearchResponse> subwayOnly = routeSearchService.search(
                "A", "C", List.of(TravelMode.SUBWAY), null, null);

        assertEquals(1, subwayOnly.size());
        assertEquals(RouteType.SHORTEST, subwayOnly.get(0).routeType());
        assertEquals(TravelMode.SUBWAY, subwayOnly.get(0).legs().get(0).mode());
    }

    @Test
    @DisplayName("IT13: 혼합(지하철+버스) 경로가 응답된다")
    void it13_혼합_지하철버스() {
        // A→B 지하철 100초, B→T1→C 버스 240초 vs A→B→C 지하철 500초(환승 포함).
        // 혼합이 이긴다.
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("A", "B", "L1", 100),
                subway("B", "C", "L2", 400),
                bus("B", "T1", "B100", 120),
                bus("T1", "C", "B100", 120)));

        List<RouteSearchResponse> result = routeSearchService.search("A", "C", null, null, null);

        assertTrue(result.size() >= 1);
        List<TravelMode> modes = result.get(0).legs().stream().map(leg -> leg.mode()).toList();
        assertTrue(modes.contains(TravelMode.BUS));
        assertTrue(modes.contains(TravelMode.SUBWAY));
    }

    private Station mockStation(String id, String name) {
        return RouteTestFixtures.mockStation(id, name);
    }
}
