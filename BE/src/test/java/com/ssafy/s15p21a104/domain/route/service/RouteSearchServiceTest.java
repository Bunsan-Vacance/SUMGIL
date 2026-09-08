package com.ssafy.s15p21a104.domain.route.service;

import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;

@ExtendWith(MockitoExtension.class)
class RouteSearchServiceTest {

    @Mock
    private StationRepository stationRepository;

    @InjectMocks
    private RouteSearchService routeSearchService;

    private Station origin;
    private Station dest;

    @BeforeEach
    void setUp() {
        origin = mockStation("0222", "한티", 37.5049, 127.0530);
        dest = mockStation("0221", "역삼", 37.5006, 127.0364);
        lenient().when(stationRepository.findById("0222")).thenReturn(Optional.of(origin));
        lenient().when(stationRepository.findById("0221")).thenReturn(Optional.of(dest));
        lenient().when(stationRepository.findById("9999")).thenReturn(Optional.empty());
    }

    @Test
    void 출발지와_도착지가_같으면_SAME_ORIGIN_DEST() {
        DomainException exception = assertThrows(DomainException.class,
                () -> routeSearchService.search("0222", "0222", null, null));

        assertEquals(ErrorType.SAME_ORIGIN_DEST, exception.getErrorType());
    }

    @Test
    void 존재하지_않는_역이면_STATION_NOT_FOUND() {
        DomainException exception = assertThrows(DomainException.class,
                () -> routeSearchService.search("9999", "0221", null, null));

        assertEquals(ErrorType.STATION_NOT_FOUND, exception.getErrorType());
    }

    @Test
    void 필터가_없으면_모든_후보를_시간순으로_반환한다() {
        List<RouteSearchResponse> result = routeSearchService.search("0222", "0221", null, null);

        assertEquals(2, result.size());
        assertEquals(RouteType.SHORTEST_WITH_BIKE, result.get(0).routeType());
        assertEquals(RouteType.SHORTEST, result.get(1).routeType());
    }

    @Test
    void SUBWAY만_허용하면_따릉이_후보는_빠진다() {
        List<RouteSearchResponse> result = routeSearchService.search(
                "0222", "0221", List.of(TravelMode.SUBWAY), null);

        assertEquals(1, result.size());
        assertEquals(RouteType.SHORTEST, result.get(0).routeType());
        assertTrue(result.get(0).legs().stream().allMatch(leg -> leg.mode() == TravelMode.SUBWAY));
    }

    private Station mockStation(String id, String name, double lat, double lng) {
        Station station = mock(Station.class);
        lenient().when(station.getStationId()).thenReturn(id);
        lenient().when(station.getName()).thenReturn(name);
        lenient().when(station.getLat()).thenReturn(lat);
        lenient().when(station.getLng()).thenReturn(lng);
        return station;
    }
}
