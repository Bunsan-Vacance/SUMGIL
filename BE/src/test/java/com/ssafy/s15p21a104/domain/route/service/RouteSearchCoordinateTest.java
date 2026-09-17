package com.ssafy.s15p21a104.domain.route.service;

import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.graphOf;
import static com.ssafy.s15p21a104.domain.route.RouteTestFixtures.subway;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.lenient;

import com.ssafy.s15p21a104.domain.route.RouteTestFixtures;
import com.ssafy.s15p21a104.domain.route.dto.request.CoordinateRouteSearchRequest;
import com.ssafy.s15p21a104.domain.route.dto.request.RoutePlaceRequest;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteLegResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry;
import com.ssafy.s15p21a104.domain.route.geometry.RailGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/**
 * 좌표 기반 경로 검색 진입점(S15P21A104-185/187) 단위 테스트.
 *
 * <p>계약·입력 검증(185)에 더해, 좌표 주변 접근 후보 연결·전체 경로 탐색(187)까지 검증한다.
 */
@ExtendWith(MockitoExtension.class)
class RouteSearchCoordinateTest {

    @Mock
    private StationRepository stationRepository;

    @Mock
    private RouteGraphRegistry graphRegistry;

    private RouteSearchService routeSearchService;

    @BeforeEach
    void setUp() {
        // A - B - C를 서로 1km 이상 떨어뜨려, 좌표별 접근 후보(500m 반경)가 각자 하나만
        // 걸리게 한다 — 안 그러면 출발·도착 좌표가 둘 다 반경 안 여러 역과 붙어 도보만으로도
        // 이어질 수 있어 "본 이동(지하철) leg가 반드시 낀다"를 검증할 수 없다.
        Map<String, RouteMapper.StationInfo> infos = new HashMap<>();
        infos.put("A", new RouteMapper.StationInfo("A", "에이역", 37.5000, 127.0000));
        infos.put("B", new RouteMapper.StationInfo("B", "비역", 37.5100, 127.0100));
        infos.put("C", new RouteMapper.StationInfo("C", "씨역", 37.5200, 127.0200));
        lenient().when(graphRegistry.stationInfos()).thenReturn(infos);
        lenient().when(graphRegistry.rentalIds()).thenReturn(java.util.Set.of());
        lenient().when(graphRegistry.transferTimes()).thenReturn(Map.of());
        lenient().when(graphRegistry.bikeStock()).thenReturn(Map.of());
        lenient().when(graphRegistry.graph()).thenReturn(graphOf(
                subway("A", "B", "L1", 100),
                subway("B", "C", "L1", 100)));
        lenient().when(graphRegistry.graphFor(
                org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.anyInt()))
                .thenAnswer(invocation -> graphRegistry.graph());

        routeSearchService = new RouteSearchService(
                stationRepository, graphRegistry, new TransferRule(180),
                new RailGeometryRegistry(null, null), RouteTestFixtures.noopWalkGeometryRegistry(),
                RouteTestFixtures.noopBikeGeometryRegistry(),
                RouteTestFixtures.noopRouteLineRepository(), RouteTestFixtures.noopBusRouteRepository(),
                RouteTestFixtures.noopCongestionRepository());
    }

    @Test
    @DisplayName("187-T1: 역 근처 좌표는 접근 도보 legs를 붙여 전체 경로를 반환한다")
    void 역근처_좌표_전체경로_반환() {
        // 출발은 A에서만, 도착은 C에서만 500m 반경 안 — 접근 도보 다음 지하철 본이동이 낀다.
        CoordinateRouteSearchRequest request = new CoordinateRouteSearchRequest(
                new RoutePlaceRequest(37.50003, 127.00003, "출발 건물"),
                new RoutePlaceRequest(37.52003, 127.02003, "도착 건물"),
                null, null, null);

        List<RouteSearchResponse> result = routeSearchService.searchByCoordinate(request);

        assertTrue(result.size() >= 1, "경로 후보가 하나 이상 있어야 한다");
        RouteSearchResponse candidate = result.get(0);
        List<RouteLegResponse> legs = candidate.legs();
        assertEquals(TravelMode.WALK, legs.get(0).mode(), "첫 leg는 좌표->접근역 도보여야 한다");
        assertEquals(TravelMode.WALK, legs.get(legs.size() - 1).mode(), "마지막 leg는 접근역->좌표 도보여야 한다");
        assertTrue(legs.stream().anyMatch(leg -> leg.mode() == TravelMode.SUBWAY), "본 이동(지하철) leg가 있어야 한다");
    }

    @Test
    @DisplayName("187-T2: 반경 밖 좌표(접근 후보 없음)는 ACCESS_CANDIDATE_NOT_FOUND")
    void 반경밖_좌표_ACCESS_CANDIDATE_NOT_FOUND() {
        // A·B·C 전부 반경(500m) 밖으로 멀리 떨어진 좌표.
        CoordinateRouteSearchRequest request = new CoordinateRouteSearchRequest(
                new RoutePlaceRequest(37.6000, 127.1000, "먼 곳"),
                new RoutePlaceRequest(37.50103, 127.00103, "도착 건물"),
                null, null, null);

        DomainException exception = assertThrows(DomainException.class,
                () -> routeSearchService.searchByCoordinate(request));

        assertEquals(ErrorType.ACCESS_CANDIDATE_NOT_FOUND, exception.getErrorType());
    }

    @Test
    @DisplayName("187-T3: 그래프 미적재면 ROUTE_DATA_NOT_READY")
    void 그래프_미적재_ROUTE_DATA_NOT_READY() {
        lenient().when(graphRegistry.graph()).thenReturn(null);
        CoordinateRouteSearchRequest request = new CoordinateRouteSearchRequest(
                new RoutePlaceRequest(37.50003, 127.00003, "출발"),
                new RoutePlaceRequest(37.50103, 127.00103, "도착"),
                null, null, null);

        DomainException exception = assertThrows(DomainException.class,
                () -> routeSearchService.searchByCoordinate(request));

        assertEquals(ErrorType.ROUTE_DATA_NOT_READY, exception.getErrorType());
    }

    @Test
    @DisplayName("출발지 좌표가 없으면 INVALID_COORDINATE")
    void 출발지_누락() {
        CoordinateRouteSearchRequest request = new CoordinateRouteSearchRequest(
                null,
                new RoutePlaceRequest(37.51, 127.04, "도착"),
                null, null, null);

        DomainException exception = assertThrows(DomainException.class,
                () -> routeSearchService.searchByCoordinate(request));

        assertEquals(ErrorType.INVALID_COORDINATE, exception.getErrorType());
    }

    @Test
    @DisplayName("위도가 누락되면 INVALID_COORDINATE")
    void 위도_누락() {
        CoordinateRouteSearchRequest request = new CoordinateRouteSearchRequest(
                new RoutePlaceRequest(null, 127.03, "출발"),
                new RoutePlaceRequest(37.51, 127.04, "도착"),
                null, null, null);

        DomainException exception = assertThrows(DomainException.class,
                () -> routeSearchService.searchByCoordinate(request));

        assertEquals(ErrorType.INVALID_COORDINATE, exception.getErrorType());
    }

    @Test
    @DisplayName("위도·경도가 유효 범위를 벗어나면 INVALID_COORDINATE")
    void 좌표_범위_초과() {
        CoordinateRouteSearchRequest request = new CoordinateRouteSearchRequest(
                new RoutePlaceRequest(91.0, 127.03, "출발"),
                new RoutePlaceRequest(37.51, 127.04, "도착"),
                null, null, null);

        DomainException exception = assertThrows(DomainException.class,
                () -> routeSearchService.searchByCoordinate(request));

        assertEquals(ErrorType.INVALID_COORDINATE, exception.getErrorType());
    }

    @Test
    @DisplayName("출발·도착 좌표가 완전히 같으면 SAME_ORIGIN_DEST")
    void 출발_도착_동일_좌표() {
        CoordinateRouteSearchRequest request = new CoordinateRouteSearchRequest(
                new RoutePlaceRequest(37.5, 127.03, "같은 곳"),
                new RoutePlaceRequest(37.5, 127.03, "같은 곳"),
                null, null, null);

        DomainException exception = assertThrows(DomainException.class,
                () -> routeSearchService.searchByCoordinate(request));

        assertEquals(ErrorType.SAME_ORIGIN_DEST, exception.getErrorType());
    }
}
