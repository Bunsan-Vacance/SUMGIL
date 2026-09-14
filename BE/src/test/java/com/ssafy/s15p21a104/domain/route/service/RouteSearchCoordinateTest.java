package com.ssafy.s15p21a104.domain.route.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.ssafy.s15p21a104.domain.route.RouteTestFixtures;
import com.ssafy.s15p21a104.domain.route.dto.request.CoordinateRouteSearchRequest;
import com.ssafy.s15p21a104.domain.route.dto.request.RoutePlaceRequest;
import com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry;
import com.ssafy.s15p21a104.domain.route.geometry.RailGeometryRegistry;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/**
 * 좌표 기반 경로 검색 진입점(S15P21A104-185)의 계약·입력 검증 단위 테스트.
 *
 * <p>이 티켓 범위는 계약·검증까지이므로, 유효한 요청의 정상 동작은 아직
 * {@link ErrorType#ACCESS_CANDIDATE_NOT_READY}다(FE 연동 fixture 참고).
 */
@ExtendWith(MockitoExtension.class)
class RouteSearchCoordinateTest {

    @Mock
    private StationRepository stationRepository;

    @Mock
    private RouteGraphRegistry graphRegistry;

    @Mock
    private TransferRule transferRule;

    @Mock
    private RailGeometryRegistry railGeometryRegistry;

    private RouteSearchService service() {
        return new RouteSearchService(stationRepository, graphRegistry, transferRule, railGeometryRegistry,
                RouteTestFixtures.noopWalkGeometryRegistry());
    }

    @Test
    @DisplayName("유효한 좌표 요청은 아직 접근 후보 연결 미구현 오류를 던진다")
    void 유효한_요청은_ACCESS_CANDIDATE_NOT_READY() {
        CoordinateRouteSearchRequest request = new CoordinateRouteSearchRequest(
                new RoutePlaceRequest(37.5, 127.03, "출발 장소"),
                new RoutePlaceRequest(37.51, 127.04, "도착 장소"),
                null, null, null);

        DomainException exception = assertThrows(DomainException.class, () -> service().searchByCoordinate(request));

        assertEquals(ErrorType.ACCESS_CANDIDATE_NOT_READY, exception.getErrorType());
    }

    @Test
    @DisplayName("출발지 좌표가 없으면 INVALID_COORDINATE")
    void 출발지_누락() {
        CoordinateRouteSearchRequest request = new CoordinateRouteSearchRequest(
                null,
                new RoutePlaceRequest(37.51, 127.04, "도착"),
                null, null, null);

        DomainException exception = assertThrows(DomainException.class, () -> service().searchByCoordinate(request));

        assertEquals(ErrorType.INVALID_COORDINATE, exception.getErrorType());
    }

    @Test
    @DisplayName("위도가 누락되면 INVALID_COORDINATE")
    void 위도_누락() {
        CoordinateRouteSearchRequest request = new CoordinateRouteSearchRequest(
                new RoutePlaceRequest(null, 127.03, "출발"),
                new RoutePlaceRequest(37.51, 127.04, "도착"),
                null, null, null);

        DomainException exception = assertThrows(DomainException.class, () -> service().searchByCoordinate(request));

        assertEquals(ErrorType.INVALID_COORDINATE, exception.getErrorType());
    }

    @Test
    @DisplayName("위도·경도가 유효 범위를 벗어나면 INVALID_COORDINATE")
    void 좌표_범위_초과() {
        CoordinateRouteSearchRequest request = new CoordinateRouteSearchRequest(
                new RoutePlaceRequest(91.0, 127.03, "출발"),
                new RoutePlaceRequest(37.51, 127.04, "도착"),
                null, null, null);

        DomainException exception = assertThrows(DomainException.class, () -> service().searchByCoordinate(request));

        assertEquals(ErrorType.INVALID_COORDINATE, exception.getErrorType());
    }

    @Test
    @DisplayName("출발·도착 좌표가 완전히 같으면 SAME_ORIGIN_DEST")
    void 출발_도착_동일_좌표() {
        CoordinateRouteSearchRequest request = new CoordinateRouteSearchRequest(
                new RoutePlaceRequest(37.5, 127.03, "같은 곳"),
                new RoutePlaceRequest(37.5, 127.03, "같은 곳"),
                null, null, null);

        DomainException exception = assertThrows(DomainException.class, () -> service().searchByCoordinate(request));

        assertEquals(ErrorType.SAME_ORIGIN_DEST, exception.getErrorType());
    }
}
