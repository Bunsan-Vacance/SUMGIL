package com.ssafy.s15p21a104.domain.bike.service;

import com.ssafy.s15p21a104.domain.bike.dto.response.BikeStationResponse;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStation;
import com.ssafy.s15p21a104.domain.bike.repository.BikeStationRepository;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;

@ExtendWith(MockitoExtension.class)
class BikeStationSearchServiceTest {

    private static final double BASE_LAT = 37.5006;
    private static final double BASE_LNG = 127.0364;

    @Mock
    private BikeStationRepository bikeStationRepository;

    @InjectMocks
    private BikeStationSearchService bikeStationSearchService;

    @Test
    void 위도가_범위_밖이면_BAD_REQUEST() {
        DomainException exception = assertThrows(DomainException.class,
                () -> bikeStationSearchService.nearby(91.0, BASE_LNG, null, null));

        assertEquals(ErrorType.BAD_REQUEST, exception.getErrorType());
    }

    @Test
    void 반경이_최대값을_넘으면_BAD_REQUEST() {
        DomainException exception = assertThrows(DomainException.class,
                () -> bikeStationSearchService.nearby(BASE_LAT, BASE_LNG, 5000, null));

        assertEquals(ErrorType.BAD_REQUEST, exception.getErrorType());
    }

    @Test
    void limit이_0이하면_BAD_REQUEST() {
        DomainException exception = assertThrows(DomainException.class,
                () -> bikeStationSearchService.nearby(BASE_LAT, BASE_LNG, null, 0));

        assertEquals(ErrorType.BAD_REQUEST, exception.getErrorType());
    }

    @Test
    void 가까운_순으로_정렬하고_반경_밖은_제외한다() {
        // 위도 0.0005도 ≈ 56m, 0.003도 ≈ 334m
        BikeStation near = mockStation("ST-1", "가까운 대여소", BASE_LAT + 0.0005, BASE_LNG, 10);
        BikeStation withinBoundingBoxButOutsideRadius = mockStation("ST-2", "박스 안 반경 밖", BASE_LAT + 0.003, BASE_LNG, 5);
        lenient().when(bikeStationRepository.findByLatBetweenAndLngBetween(any(), any(), any(), any()))
                .thenReturn(List.of(withinBoundingBoxButOutsideRadius, near));

        List<BikeStationResponse> result = bikeStationSearchService.nearby(BASE_LAT, BASE_LNG, 200, null);

        assertEquals(1, result.size());
        assertEquals("ST-1", result.get(0).rentalId());
    }

    private BikeStation mockStation(String rentalId, String name, double lat, double lng, int dockCount) {
        BikeStation station = mock(BikeStation.class);
        lenient().when(station.getRentalId()).thenReturn(rentalId);
        lenient().when(station.getName()).thenReturn(name);
        lenient().when(station.getLat()).thenReturn(lat);
        lenient().when(station.getLng()).thenReturn(lng);
        lenient().when(station.getDockCount()).thenReturn(dockCount);
        return station;
    }
}
