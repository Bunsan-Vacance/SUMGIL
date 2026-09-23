package com.ssafy.s15p21a104.domain.bike.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.ssafy.s15p21a104.domain.bike.dto.response.BikePredictionResponse;
import com.ssafy.s15p21a104.domain.bike.dto.response.BikePredictionSource;
import com.ssafy.s15p21a104.domain.bike.dto.response.BikePredictionStatus;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStation;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPred;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPredId;
import com.ssafy.s15p21a104.domain.bike.repository.BikeStationRepository;
import com.ssafy.s15p21a104.domain.bike.repository.BikeStockPredDailyRepository;
import com.ssafy.s15p21a104.domain.bike.repository.BikeStockPredRepository;
import com.ssafy.s15p21a104.domain.bike.stock.BikeStockReader;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/**
 * S15P21A104-237 따릉이 도착 예측 RED (FE-BE 통합 계약 §6).
 */
@ExtendWith(MockitoExtension.class)
class BikePrediction237Test {

    private static final String ARRIVAL = "2026-09-17T08:38:00+09:00";

    @Mock
    private BikeStationRepository bikeStationRepository;

    @Mock
    private BikeStockReader bikeStockReader;

    @Mock
    private BikeStockPredRepository bikeStockPredRepository;

    /**
     * 309 날짜축 표. 여기서는 늘 비어 있다(Mockito 기본값 Optional.empty) — 날짜축이 비면 응답이 237 그대로라는 것을
     * 이 테스트 전체가 그대로 보장한다. 없으면 @InjectMocks 가 null 을 넣어 prediction() 이 NPE 로 죽는다.
     */
    @Mock
    private BikeStockPredDailyRepository bikeStockPredDailyRepository;

    @InjectMocks
    private BikeStationSearchService bikeStationSearchService;

    private void givenStation(String rentalId) {
        BikeStation station = mock(BikeStation.class);
        // P4처럼 arrivalTime 파싱에서 먼저 떨어지는 케이스에서는 호출되지 않는다.
        lenient().when(station.getRentalId()).thenReturn(rentalId);
        when(bikeStationRepository.findById(rentalId)).thenReturn(Optional.of(station));
    }

    private void givenPredRow(String rentalId, int dow, int slot) {
        BikeStockPred pred = mock(BikeStockPred.class);
        when(pred.getExpBikes()).thenReturn(new BigDecimal("6.4"));
        when(pred.getPEmpty()).thenReturn(new BigDecimal("0.180"));
        when(pred.getSource()).thenReturn("model");
        when(pred.getUpdatedAt()).thenReturn(
                OffsetDateTime.of(2026, 9, 17, 8, 30, 0, 0, ZoneOffset.of("+09:00")));
        when(bikeStockPredRepository.findById(new BikeStockPredId(rentalId, dow, slot)))
                .thenReturn(Optional.of(pred));
    }

    @Test
    @DisplayName("237-P1: 예측 행이 있으면 AVAILABLE이다")
    void p1_available() {
        givenStation("ST-1");
        // 2026-09-17 목요일 → dow 0, 08:38 → slot 17.
        givenPredRow("ST-1", 0, 17);

        BikePredictionResponse response =
                bikeStationSearchService.prediction("ST-1", ARRIVAL);

        assertEquals(BikePredictionStatus.AVAILABLE, response.status());
        assertEquals(6, response.predictedBikes());
        assertEquals(0.82, response.availabilityProbability(), 1e-9);
        assertEquals("ST-1", response.rentalId());
        assertEquals(OffsetDateTime.parse(ARRIVAL), response.arrivalTime());
        assertEquals(BikePredictionSource.MODEL, response.source());
    }

    @Test
    @DisplayName("237-P2: 예측 행이 없으면 UNAVAILABLE + 값 null이다")
    void p2_unavailable() {
        givenStation("ST-1");
        when(bikeStockPredRepository.findById(any())).thenReturn(Optional.empty());

        BikePredictionResponse response =
                bikeStationSearchService.prediction("ST-1", ARRIVAL);

        assertEquals(BikePredictionStatus.UNAVAILABLE, response.status());
        assertNull(response.predictedBikes());
        assertNull(response.availabilityProbability());
        assertNull(response.predictedAt());
        assertEquals(OffsetDateTime.parse(ARRIVAL), response.arrivalTime());
        assertEquals("ST-1", response.rentalId());
    }

    @Test
    @DisplayName("237-P3: 미등록 대여소는 404다")
    void p3_미등록404() {
        when(bikeStationRepository.findById("NOPE")).thenReturn(Optional.empty());

        DomainException exception = assertThrows(DomainException.class,
                () -> bikeStationSearchService.prediction("NOPE", ARRIVAL));

        assertEquals(ErrorType.BIKE_STATION_NOT_FOUND, exception.getErrorType());
    }

    @Test
    @DisplayName("237-P4: arrivalTime 없거나 깨지면 400이다")
    void p4_시각오류400() {
        givenStation("ST-1");

        assertEquals(ErrorType.BAD_REQUEST, assertThrows(DomainException.class,
                () -> bikeStationSearchService.prediction("ST-1", null)).getErrorType());
        assertEquals(ErrorType.BAD_REQUEST, assertThrows(DomainException.class,
                () -> bikeStationSearchService.prediction("ST-1", "어제")).getErrorType());
    }

    @Test
    @DisplayName("237-P5: avg 산출물은 MOCK 출처다")
    void p5_avg는MOCK() {
        givenStation("ST-1");
        BikeStockPred pred = mock(BikeStockPred.class);
        when(pred.getExpBikes()).thenReturn(new BigDecimal("3.0"));
        when(pred.getPEmpty()).thenReturn(new BigDecimal("0.500"));
        when(pred.getSource()).thenReturn("avg");
        when(pred.getUpdatedAt()).thenReturn(
                OffsetDateTime.of(2026, 9, 17, 8, 30, 0, 0, ZoneOffset.of("+09:00")));
        when(bikeStockPredRepository.findById(any())).thenReturn(Optional.of(pred));

        BikePredictionResponse response =
                bikeStationSearchService.prediction("ST-1", ARRIVAL);

        assertEquals(BikePredictionStatus.AVAILABLE, response.status());
        assertEquals(BikePredictionSource.MOCK, response.source());
    }
}
