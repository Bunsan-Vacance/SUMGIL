package com.ssafy.s15p21a104.domain.bike.service;

import com.ssafy.s15p21a104.domain.bike.dto.response.BikeStationResponse;
import com.ssafy.s15p21a104.domain.bike.dto.response.BikeStockResponse;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStation;
import com.ssafy.s15p21a104.domain.bike.repository.BikeStationRepository;
import com.ssafy.s15p21a104.domain.bike.stock.BikeStock;
import com.ssafy.s15p21a104.domain.bike.stock.BikeStockReader;
import com.ssafy.s15p21a104.domain.bike.stock.BikeStockStatus;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import java.time.OffsetDateTime;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
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

    @Mock
    private BikeStockReader bikeStockReader;

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
        lenient().when(bikeStockReader.find(any())).thenReturn(new BikeStock(null, null, BikeStockStatus.UNAVAILABLE));

        List<BikeStationResponse> result = bikeStationSearchService.nearby(BASE_LAT, BASE_LNG, 200, null);

        assertEquals(1, result.size());
        assertEquals("ST-1", result.get(0).rentalId());
    }

    @Test
    @DisplayName("156-AC1: 재고 캐시가 있으면 nearby 응답에 노출된다")
    void 재고_있으면_nearby에_노출() {
        BikeStation near = mockStation("ST-1", "가까운 대여소", BASE_LAT + 0.0005, BASE_LNG, 10);
        lenient().when(bikeStationRepository.findByLatBetweenAndLngBetween(any(), any(), any(), any()))
                .thenReturn(List.of(near));
        OffsetDateTime updatedAt = OffsetDateTime.parse("2026-09-17T10:00:00+09:00");
        lenient().when(bikeStockReader.find("ST-1")).thenReturn(new BikeStock(7, updatedAt, BikeStockStatus.AVAILABLE));

        List<BikeStationResponse> result = bikeStationSearchService.nearby(BASE_LAT, BASE_LNG, 200, null);

        assertEquals(1, result.size());
        assertEquals(7, result.get(0).availableBikes());
        assertEquals(updatedAt, result.get(0).stockUpdatedAt());
    }

    @Test
    @DisplayName("156-AC1: 재고 캐시가 없으면 nearby 응답 필드는 null이다(에러 아님)")
    void 재고_없으면_nearby에서_null() {
        BikeStation near = mockStation("ST-1", "가까운 대여소", BASE_LAT + 0.0005, BASE_LNG, 10);
        lenient().when(bikeStationRepository.findByLatBetweenAndLngBetween(any(), any(), any(), any()))
                .thenReturn(List.of(near));
        lenient().when(bikeStockReader.find("ST-1")).thenReturn(new BikeStock(null, null, BikeStockStatus.UNAVAILABLE));

        List<BikeStationResponse> result = bikeStationSearchService.nearby(BASE_LAT, BASE_LNG, 200, null);

        assertNull(result.get(0).availableBikes());
        assertNull(result.get(0).stockUpdatedAt());
    }

    @Test
    @DisplayName("등록되지 않은 rentalId로 단건 조회하면 BIKE_STATION_NOT_FOUND")
    void 단건조회_없는_대여소() {
        lenient().when(bikeStationRepository.findById("ST-404")).thenReturn(Optional.empty());

        DomainException exception = assertThrows(DomainException.class,
                () -> bikeStationSearchService.stock("ST-404"));

        assertEquals(ErrorType.BIKE_STATION_NOT_FOUND, exception.getErrorType());
    }

    @Test
    @DisplayName("등록된 대여소는 재고 상태(AVAILABLE/STALE/UNAVAILABLE)를 그대로 전달한다")
    void 단건조회_상태_전달() {
        BikeStation station = mockStation("ST-1", "가까운 대여소", BASE_LAT, BASE_LNG, 10);
        lenient().when(bikeStationRepository.findById("ST-1")).thenReturn(Optional.of(station));
        OffsetDateTime updatedAt = OffsetDateTime.parse("2026-09-17T09:50:00+09:00");
        lenient().when(bikeStockReader.find("ST-1")).thenReturn(new BikeStock(3, updatedAt, BikeStockStatus.STALE));

        BikeStockResponse response = bikeStationSearchService.stock("ST-1");

        assertEquals("ST-1", response.rentalId());
        assertEquals(3, response.availableBikes());
        assertEquals(updatedAt, response.stockUpdatedAt());
        assertEquals(BikeStockStatus.STALE, response.status());
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
