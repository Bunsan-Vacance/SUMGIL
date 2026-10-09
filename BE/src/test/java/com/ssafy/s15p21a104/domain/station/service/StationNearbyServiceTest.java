package com.ssafy.s15p21a104.domain.station.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ssafy.s15p21a104.domain.station.dto.response.StationLineResponse;
import com.ssafy.s15p21a104.domain.station.dto.response.StationNearbyResponse;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class StationNearbyServiceTest {

    // 위도 0.001도는 약 111m다.
    private static final double LAT = 37.5000;
    private static final double LNG = 127.0000;

    @Mock
    private StationRepository stationRepository;

    @Mock
    private StationLineLookup stationLineLookup;

    private StationNearbyService service;

    @BeforeEach
    void setUp() {
        service = new StationNearbyService(stationRepository, stationLineLookup);
        lenient().when(stationLineLookup.groupLineIdsByStation(any())).thenReturn(Map.of());
        lenient().when(stationLineLookup.lineNamesFor(any())).thenReturn(Map.of());
    }

    private void stubCandidates(Station... stations) {
        when(stationRepository.findByLatBetweenAndLngBetween(anyDouble(), anyDouble(), anyDouble(), anyDouble()))
                .thenReturn(List.of(stations));
    }

    @Test
    @DisplayName("반경 안의 역만 거리순으로 돌려주고 반경 밖·좌표 없는 역은 제외한다")
    void 반경_필터_거리순() {
        Station far = station("F", "먼역", LAT + 0.02, LNG);
        Station second = station("B", "둘째", LAT + 0.003, LNG);
        Station first = station("A", "첫째", LAT + 0.001, LNG);
        Station noCoordinate = station("N", "좌표없음", null, null);
        stubCandidates(far, second, noCoordinate, first);

        List<StationNearbyResponse> result = service.nearby(LAT, LNG, null, null);

        assertEquals(List.of("A", "B"), result.stream().map(StationNearbyResponse::stationId).toList());
        assertTrue(result.get(0).distanceMeters() > 100 && result.get(0).distanceMeters() < 120);
        assertTrue(result.get(0).distanceMeters() < result.get(1).distanceMeters());
    }

    @Test
    @DisplayName("limit만큼만 돌려준다")
    void limit_적용() {
        stubCandidates(
                station("A", "첫째", LAT + 0.001, LNG),
                station("B", "둘째", LAT + 0.002, LNG),
                station("C", "셋째", LAT + 0.003, LNG));

        List<StationNearbyResponse> result = service.nearby(LAT, LNG, null, 2);

        assertEquals(List.of("A", "B"), result.stream().map(StationNearbyResponse::stationId).toList());
    }

    @Test
    @DisplayName("환승역은 노선을 lineId 순으로 모으고 노선 없는 역은 빈 배열이다")
    void 노선_묶기() {
        stubCandidates(
                station("T", "환승역", LAT + 0.001, LNG),
                station("X", "노선없음", LAT + 0.002, LNG));
        when(stationLineLookup.groupLineIdsByStation(any()))
                .thenReturn(Map.of("T", Set.of("1007", "1002")));
        when(stationLineLookup.lineNamesFor(any()))
                .thenReturn(Map.of("1002", "2호선", "1007", "7호선"));

        List<StationNearbyResponse> result = service.nearby(LAT, LNG, null, null);

        assertEquals(2, result.size());
        assertEquals(
                List.of(new StationLineResponse("1002", "2호선"), new StationLineResponse("1007", "7호선")),
                result.get(0).lines());
        assertTrue(result.get(1).lines().isEmpty());
    }

    @Test
    @DisplayName("노선 조회는 결과 역 전체에 대해 한 번만 한다")
    @SuppressWarnings("unchecked")
    void 노선조회_1회() {
        stubCandidates(
                station("A", "첫째", LAT + 0.001, LNG),
                station("B", "둘째", LAT + 0.002, LNG));

        service.nearby(LAT, LNG, null, null);

        ArgumentCaptor<Set<String>> ids = ArgumentCaptor.forClass(Set.class);
        verify(stationLineLookup, times(1)).groupLineIdsByStation(ids.capture());
        assertEquals(Set.of("A", "B"), ids.getValue());
        verify(stationLineLookup, times(1)).lineNamesFor(any());
    }

    @Test
    @DisplayName("결과가 없으면 빈 배열이고 노선 조회를 하지 않는다")
    void 결과없음() {
        stubCandidates(station("F", "먼역", LAT + 0.02, LNG));

        assertTrue(service.nearby(LAT, LNG, null, null).isEmpty());
        verify(stationLineLookup, never()).groupLineIdsByStation(any());
    }

    @Test
    @DisplayName("좌표가 없거나 범위 밖이면 INVALID_COORDINATE")
    void 좌표_오류() {
        assertEquals(ErrorType.INVALID_COORDINATE, errorOf(() -> service.nearby(null, LNG, null, null)));
        assertEquals(ErrorType.INVALID_COORDINATE, errorOf(() -> service.nearby(LAT, null, null, null)));
        assertEquals(ErrorType.INVALID_COORDINATE, errorOf(() -> service.nearby(91.0, LNG, null, null)));
        assertEquals(ErrorType.INVALID_COORDINATE, errorOf(() -> service.nearby(LAT, -181.0, null, null)));
    }

    @Test
    @DisplayName("반경 0·3001, 개수 0·51은 BAD_REQUEST")
    void 범위_오류() {
        assertEquals(ErrorType.BAD_REQUEST, errorOf(() -> service.nearby(LAT, LNG, 0, null)));
        assertEquals(ErrorType.BAD_REQUEST, errorOf(() -> service.nearby(LAT, LNG, 3001, null)));
        assertEquals(ErrorType.BAD_REQUEST, errorOf(() -> service.nearby(LAT, LNG, null, 0)));
        assertEquals(ErrorType.BAD_REQUEST, errorOf(() -> service.nearby(LAT, LNG, null, 51)));
    }

    @Test
    @DisplayName("반경 기본값은 1000m, 개수 기본값은 20개다")
    void 기본값() {
        List<Station> many = new java.util.ArrayList<>();
        for (int i = 0; i < 30; i++) {
            many.add(station("S" + i, "역" + i, LAT + 0.0001 * (i + 1), LNG));
        }
        many.add(station("OUT", "경계밖", LAT + 0.0095, LNG)); // 약 1057m
        stubCandidates(many.toArray(new Station[0]));

        List<StationNearbyResponse> result = service.nearby(LAT, LNG, null, null);

        assertEquals(StationNearbyService.DEFAULT_LIMIT, result.size());
        assertTrue(result.stream().noneMatch(r -> r.stationId().equals("OUT")));
        // 반경 기본값 1000m가 적용되는지: 20개 제한 없이 2개만 후보일 때 경계 밖 역이 빠진다.
        stubCandidates(station("IN", "경계안", LAT + 0.008, LNG), station("OUT", "경계밖", LAT + 0.0095, LNG));
        assertEquals(List.of("IN"), service.nearby(LAT, LNG, null, 5).stream()
                .map(StationNearbyResponse::stationId).toList());
    }

    private ErrorType errorOf(org.junit.jupiter.api.function.Executable executable) {
        return assertThrows(DomainException.class, executable).getErrorType();
    }

    private Station station(String id, String name, Double lat, Double lng) {
        Station station = mock(Station.class);
        lenient().when(station.getStationId()).thenReturn(id);
        lenient().when(station.getName()).thenReturn(name);
        lenient().when(station.getLat()).thenReturn(lat);
        lenient().when(station.getLng()).thenReturn(lng);
        return station;
    }
}
