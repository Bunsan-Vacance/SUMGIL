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
import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPredDaily;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPredDailyId;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPredId;
import com.ssafy.s15p21a104.domain.bike.repository.BikeStationRepository;
import com.ssafy.s15p21a104.domain.bike.repository.BikeStockPredDailyRepository;
import com.ssafy.s15p21a104.domain.bike.repository.BikeStockPredRepository;
import com.ssafy.s15p21a104.domain.bike.stock.BikeStockReader;
import java.math.BigDecimal;
import java.time.LocalDate;
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
 * S15P21A104-309 따릉이 도착 예측 — 날짜축(모델) 표 우선, 없으면 요일축(평균) 표.
 *
 * <p>날짜축 표는 비어 있어도 되는 표다. 비어 있으면 응답은 237 그대로여야 한다 — 그래서 배포 순서가 자유롭고,
 * AI 가 모델 산출물을 멈추면 평균값으로 돌아간다. {@code source} 열거형(MODEL|MOCK)은 FE 계약이라 바꾸지 않는다.
 */
@ExtendWith(MockitoExtension.class)
class BikePredictionDailyTest {

    /** 2026-09-23(수) 17:40 KST → 날짜 2026-09-23, 평일 dow 0, 슬롯 35. */
    private static final String ARRIVAL = "2026-09-23T17:40:00+09:00";
    private static final LocalDate DATE = LocalDate.of(2026, 9, 23);
    private static final int SLOT = 35;
    private static final OffsetDateTime GENERATED = OffsetDateTime.of(2026, 9, 23, 0, 30, 0, 0, ZoneOffset.UTC);
    private static final OffsetDateTime LOADED = OffsetDateTime.of(2026, 9, 23, 1, 0, 26, 0, ZoneOffset.UTC);

    @Mock
    private BikeStationRepository bikeStationRepository;

    @Mock
    private BikeStockReader bikeStockReader;

    @Mock
    private BikeStockPredRepository bikeStockPredRepository;

    @Mock
    private BikeStockPredDailyRepository bikeStockPredDailyRepository;

    @InjectMocks
    private BikeStationSearchService bikeStationSearchService;

    private void givenStation(String rentalId) {
        BikeStation station = mock(BikeStation.class);
        lenient().when(station.getRentalId()).thenReturn(rentalId);
        when(bikeStationRepository.findById(rentalId)).thenReturn(Optional.of(station));
    }

    private void givenDailyRow(String rentalId, LocalDate date, int slot, String expBikes, String pEmpty) {
        BikeStockPredDaily pred = mock(BikeStockPredDaily.class);
        when(pred.getExpBikes()).thenReturn(new BigDecimal(expBikes));
        when(pred.getPEmpty()).thenReturn(new BigDecimal(pEmpty));
        when(pred.getSource()).thenReturn("model");
        when(pred.getGeneratedAt()).thenReturn(GENERATED);
        when(bikeStockPredDailyRepository.findById(new BikeStockPredDailyId(rentalId, date, slot)))
                .thenReturn(Optional.of(pred));
    }

    private void givenAvgRow(String rentalId, int dow, int slot) {
        BikeStockPred pred = mock(BikeStockPred.class);
        when(pred.getExpBikes()).thenReturn(new BigDecimal("6.6"));
        when(pred.getPEmpty()).thenReturn(new BigDecimal("0.066"));
        when(pred.getSource()).thenReturn("avg");
        when(pred.getUpdatedAt()).thenReturn(LOADED);
        when(bikeStockPredRepository.findById(new BikeStockPredId(rentalId, dow, slot)))
                .thenReturn(Optional.of(pred));
    }

    @Test
    @DisplayName("309-D1: 날짜축 행이 있으면 그 값 · MODEL · predictedAt=산출 시각(generated_at) — 평균표는 보지 않는다")
    void d1_날짜축_우선() {
        givenStation("ST-1577");
        givenDailyRow("ST-1577", DATE, SLOT, "4.4", "0.180");

        BikePredictionResponse response = bikeStationSearchService.prediction("ST-1577", ARRIVAL);

        assertEquals(BikePredictionStatus.AVAILABLE, response.status());
        assertEquals(4, response.predictedBikes());
        assertEquals(0.82, response.availabilityProbability(), 1e-9);
        assertEquals(BikePredictionSource.MODEL, response.source());
        assertEquals(GENERATED, response.predictedAt());
        verify(bikeStockPredRepository, never()).findById(any());
    }

    @Test
    @DisplayName("309-D2: 날짜축 행이 없으면 평균표 — 응답은 237 그대로(MOCK · predictedAt=적재 시각)")
    void d2_평균표_폴백() {
        givenStation("ST-1577");
        when(bikeStockPredDailyRepository.findById(any())).thenReturn(Optional.empty());
        givenAvgRow("ST-1577", 0, SLOT);

        BikePredictionResponse response = bikeStationSearchService.prediction("ST-1577", ARRIVAL);

        assertEquals(BikePredictionStatus.AVAILABLE, response.status());
        assertEquals(7, response.predictedBikes());
        assertEquals(BikePredictionSource.MOCK, response.source());
        assertEquals(LOADED, response.predictedAt());
    }

    @Test
    @DisplayName("309-D3: 둘 다 없으면 UNAVAILABLE + 값 null — 0 으로 바꾸지 않는다")
    void d3_둘다_없음() {
        givenStation("ST-1577");
        when(bikeStockPredDailyRepository.findById(any())).thenReturn(Optional.empty());
        when(bikeStockPredRepository.findById(any())).thenReturn(Optional.empty());

        BikePredictionResponse response = bikeStationSearchService.prediction("ST-1577", ARRIVAL);

        assertEquals(BikePredictionStatus.UNAVAILABLE, response.status());
        assertNull(response.predictedBikes());
        assertNull(response.predictedAt());
    }

    @Test
    @DisplayName("309-D4: 날짜는 KST 로 자른다 — UTC 15:40 는 KST 다음 날 00:40 이라 그 날짜·슬롯 1 을 본다")
    void d4_KST_날짜경계() {
        givenStation("ST-1577");
        // 2026-09-22T15:40Z = 2026-09-23 00:40 KST. UTC 날짜(22일)로 자르면 전날 표를 본다.
        givenDailyRow("ST-1577", DATE, 1, "2.0", "0.500");

        BikePredictionResponse response = bikeStationSearchService.prediction("ST-1577", "2026-09-22T15:40:00Z");

        assertEquals(BikePredictionSource.MODEL, response.source());
        assertEquals(2, response.predictedBikes());
    }
}
