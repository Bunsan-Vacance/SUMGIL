package com.ssafy.s15p21a104.domain.bike.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ssafy.s15p21a104.domain.bike.dto.response.BikePredictionResponse;
import com.ssafy.s15p21a104.domain.bike.dto.response.BikePredictionSource;
import com.ssafy.s15p21a104.domain.bike.dto.response.BikePredictionStatus;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStation;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPred;
import com.ssafy.s15p21a104.domain.bike.eta.BikeEtaReader;
import com.ssafy.s15p21a104.domain.bike.eta.BikeEtaStock;
import com.ssafy.s15p21a104.domain.bike.repository.BikeStationRepository;
import com.ssafy.s15p21a104.domain.bike.repository.BikeStockPredRepository;
import com.ssafy.s15p21a104.domain.bike.stock.BikeStockReader;
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
 * S15P21A104-309 따릉이 도착 예측 — AI 실시간 모델 먼저, 못 쓰면 평균표.
 *
 * <p>모델 값을 쓸 수 있는지(도착까지 30분 이내 · 호출 성공 · 대여소별 모델 값)는 {@link BikeEtaReader} 가 판정한다.
 * 서비스는 "값이 있으면 MODEL, 없으면 237 그대로" 만 책임진다. {@code source} 열거형(MODEL|MOCK)은 FE 계약이라 바꾸지 않는다.
 */
@ExtendWith(MockitoExtension.class)
class BikePredictionEtaTest {

    private static final String ARRIVAL = "2026-09-23T10:15:00+09:00";
    private static final OffsetDateTime CALLED_AT = OffsetDateTime.of(2026, 9, 23, 1, 0, 0, 0, ZoneOffset.UTC);
    private static final OffsetDateTime LOADED = OffsetDateTime.of(2026, 9, 23, 1, 0, 26, 0, ZoneOffset.UTC);

    @Mock
    private BikeStationRepository bikeStationRepository;

    @Mock
    private BikeStockReader bikeStockReader;

    @Mock
    private BikeStockPredRepository bikeStockPredRepository;

    @Mock
    private BikeEtaReader bikeEtaReader;

    @InjectMocks
    private BikeStationSearchService bikeStationSearchService;

    private void givenStation(String rentalId) {
        BikeStation station = mock(BikeStation.class);
        lenient().when(station.getRentalId()).thenReturn(rentalId);
        when(bikeStationRepository.findById(rentalId)).thenReturn(Optional.of(station));
    }

    private void givenAvgRow() {
        BikeStockPred pred = mock(BikeStockPred.class);
        when(pred.getExpBikes()).thenReturn(new BigDecimal("6.6"));
        when(pred.getPEmpty()).thenReturn(new BigDecimal("0.066"));
        when(pred.getSource()).thenReturn("avg");
        when(pred.getUpdatedAt()).thenReturn(LOADED);
        when(bikeStockPredRepository.findById(any())).thenReturn(Optional.of(pred));
    }

    @Test
    @DisplayName("309-E1: AI 모델 값이 있으면 그 값 · MODEL · predictedAt=부른 시각 — 평균표는 보지 않는다")
    void e1_모델_우선() {
        givenStation("ST-1577");
        when(bikeEtaReader.find("ST-1577", OffsetDateTime.parse(ARRIVAL)))
                .thenReturn(Optional.of(new BikeEtaStock(1, 0.685, CALLED_AT)));

        BikePredictionResponse response = bikeStationSearchService.prediction("ST-1577", ARRIVAL);

        assertEquals(BikePredictionStatus.AVAILABLE, response.status());
        assertEquals(1, response.predictedBikes());
        assertEquals(0.685, response.availabilityProbability(), 1e-12);
        assertEquals(CALLED_AT, response.predictedAt());
        assertEquals(BikePredictionSource.MODEL, response.source());
        assertEquals(OffsetDateTime.parse(ARRIVAL), response.arrivalTime());
        verify(bikeStockPredRepository, never()).findById(any());
    }

    @Test
    @DisplayName("309-E2: 모델 값이 없으면 평균표 — 응답은 237 그대로(MOCK · predictedAt=적재 시각)")
    void e2_평균표_폴백() {
        givenStation("ST-1577");
        when(bikeEtaReader.find(any(), any())).thenReturn(Optional.empty());
        givenAvgRow();

        BikePredictionResponse response = bikeStationSearchService.prediction("ST-1577", ARRIVAL);

        assertEquals(BikePredictionStatus.AVAILABLE, response.status());
        assertEquals(7, response.predictedBikes());
        assertEquals(BikePredictionSource.MOCK, response.source());
        assertEquals(LOADED, response.predictedAt());
    }

    @Test
    @DisplayName("309-E3: 둘 다 없으면 UNAVAILABLE + 값 null")
    void e3_둘다_없음() {
        givenStation("ST-1577");
        when(bikeEtaReader.find(any(), any())).thenReturn(Optional.empty());
        when(bikeStockPredRepository.findById(any())).thenReturn(Optional.empty());

        BikePredictionResponse response = bikeStationSearchService.prediction("ST-1577", ARRIVAL);

        assertEquals(BikePredictionStatus.UNAVAILABLE, response.status());
        assertNull(response.predictedBikes());
        assertNull(response.predictedAt());
    }
}
