package com.ssafy.s15p21a104.domain.ops.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.ssafy.s15p21a104.domain.bike.dto.response.BikePredictionStatus;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStation;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPred;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPredId;
import com.ssafy.s15p21a104.domain.bike.repository.BikeStationRepository;
import com.ssafy.s15p21a104.domain.bike.stock.BikeStock;
import com.ssafy.s15p21a104.domain.bike.stock.BikeStockReader;
import com.ssafy.s15p21a104.domain.bike.stock.BikeStockStatus;
import com.ssafy.s15p21a104.domain.ops.dto.response.BikeStockOverviewItem;
import com.ssafy.s15p21a104.domain.ops.dto.response.BikeStockOverviewResponse;
import com.ssafy.s15p21a104.domain.ops.dto.response.OpsPredictionSource;
import com.ssafy.s15p21a104.domain.ops.repository.OpsBikeStockPredRepository;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class OpsBikeStockServiceTest {

    private static final double SW_LAT = 37.49;
    private static final double SW_LNG = 127.02;
    private static final double NE_LAT = 37.51;
    private static final double NE_LNG = 127.05;
    private static final double CENTER_LAT = 37.50;
    private static final double CENTER_LNG = 127.035;

    // 2026-10-03(토) 12:00 KST = 03:00Z → dow_type 1, time_slot 24
    private static final Instant NOW = Instant.parse("2026-10-03T03:00:00Z");
    private static final Clock CLOCK = Clock.fixed(NOW, ZoneId.of("UTC"));

    @Mock
    private BikeStationRepository bikeStationRepository;

    @Mock
    private BikeStockReader bikeStockReader;

    @Mock
    private OpsBikeStockPredRepository predRepository;

    private OpsBikeStockService service;

    @BeforeEach
    void setUp() {
        service = new OpsBikeStockService(bikeStationRepository, bikeStockReader, predRepository, CLOCK);
    }

    @Test
    @DisplayName("bbox가 뒤집히면 BAD_REQUEST")
    void bboxInverted() {
        DomainException lat = assertThrows(DomainException.class,
                () -> service.overview(NE_LAT, SW_LNG, SW_LAT, NE_LNG, null, null));
        DomainException lng = assertThrows(DomainException.class,
                () -> service.overview(SW_LAT, NE_LNG, NE_LAT, SW_LNG, null, null));

        assertEquals(ErrorType.BAD_REQUEST, lat.getErrorType());
        assertEquals(ErrorType.BAD_REQUEST, lng.getErrorType());
    }

    @Test
    @DisplayName("좌표가 범위 밖이면 BAD_REQUEST")
    void coordinateOutOfRange() {
        DomainException lat = assertThrows(DomainException.class,
                () -> service.overview(SW_LAT, SW_LNG, 91.0, NE_LNG, null, null));
        DomainException lng = assertThrows(DomainException.class,
                () -> service.overview(SW_LAT, SW_LNG, NE_LAT, 181.0, null, null));

        assertEquals(ErrorType.BAD_REQUEST, lat.getErrorType());
        assertEquals(ErrorType.BAD_REQUEST, lng.getErrorType());
    }

    @Test
    @DisplayName("limit이 1~500 밖이면 BAD_REQUEST")
    void limitOutOfRange() {
        assertEquals(ErrorType.BAD_REQUEST, assertThrows(DomainException.class,
                () -> service.overview(SW_LAT, SW_LNG, NE_LAT, NE_LNG, null, 0)).getErrorType());
        assertEquals(ErrorType.BAD_REQUEST, assertThrows(DomainException.class,
                () -> service.overview(SW_LAT, SW_LNG, NE_LAT, NE_LNG, null, 501)).getErrorType());
    }

    @Test
    @DisplayName("arrivalTime 형식이 깨지면 BAD_REQUEST")
    void badArrivalTime() {
        DomainException exception = assertThrows(DomainException.class,
                () -> service.overview(SW_LAT, SW_LNG, NE_LAT, NE_LNG, "내일 오후", null));

        assertEquals(ErrorType.BAD_REQUEST, exception.getErrorType());
    }

    @Test
    @DisplayName("limit을 넘으면 bbox 중심에 가까운 순으로 자르고 truncated=true")
    void limitCutKeepsNearest() {
        BikeStation far = station("FAR", CENTER_LAT + 0.009, CENTER_LNG);
        BikeStation near = station("NEAR", CENTER_LAT + 0.0005, CENTER_LNG);
        BikeStation mid = station("MID", CENTER_LAT + 0.004, CENTER_LNG);
        givenStations(far, near, mid);
        lenient().when(bikeStockReader.find(any())).thenReturn(unavailableStock());

        BikeStockOverviewResponse response = service.overview(SW_LAT, SW_LNG, NE_LAT, NE_LNG, null, 2);

        assertTrue(response.truncated());
        assertEquals(2, response.count());
        assertEquals(List.of("NEAR", "MID"), response.items().stream().map(BikeStockOverviewItem::rentalId).toList());
    }

    @Test
    @DisplayName("limit 이하면 truncated=false")
    void notTruncated() {
        givenStations(station("A", CENTER_LAT, CENTER_LNG));
        lenient().when(bikeStockReader.find(any())).thenReturn(unavailableStock());

        BikeStockOverviewResponse response = service.overview(SW_LAT, SW_LNG, NE_LAT, NE_LNG, null, 1);

        assertFalse(response.truncated());
        assertEquals(1, response.count());
    }

    @Test
    @DisplayName("재고가 UNAVAILABLE이면 값은 null로 유지한다")
    void stockUnavailableKeepsNulls() {
        givenStations(station("A", CENTER_LAT, CENTER_LNG));
        when(bikeStockReader.find("A")).thenReturn(unavailableStock());

        BikeStockOverviewItem item = service.overview(SW_LAT, SW_LNG, NE_LAT, NE_LNG, null, null).items().get(0);

        assertEquals(BikeStockStatus.UNAVAILABLE, item.stockStatus());
        assertNull(item.availableBikes());
        assertNull(item.rackCount());
        assertNull(item.stockUpdatedAt());
    }

    @Test
    @DisplayName("예측 행이 있으면 AVAILABLE·TABLE, 재고는 반올림, 확률은 1-pEmpty를 0~1로 제한")
    void predictionPresent() {
        OffsetDateTime stockAt = OffsetDateTime.parse("2026-10-03T11:59:00+09:00");
        OffsetDateTime predAt = OffsetDateTime.parse("2026-10-03T00:10:00+09:00");
        givenStations(station("A", CENTER_LAT, CENTER_LNG), station("B", CENTER_LAT + 0.001, CENTER_LNG));
        when(bikeStockReader.find("A")).thenReturn(new BikeStock(4, 15, stockAt, BikeStockStatus.AVAILABLE));
        when(bikeStockReader.find("B")).thenReturn(unavailableStock());
        givenPreds(pred("A", "2.5", "0.200", predAt),
                        pred("B", "0.4", "1.200", predAt));

        List<BikeStockOverviewItem> items = service.overview(SW_LAT, SW_LNG, NE_LAT, NE_LNG, null, null).items();
        BikeStockOverviewItem a = items.get(0);
        BikeStockOverviewItem b = items.get(1);

        assertEquals(BikePredictionStatus.AVAILABLE, a.predictionStatus());
        assertEquals(OpsPredictionSource.TABLE, a.predictionSource());
        assertEquals(3, a.predictedBikes());
        assertEquals(0.8, a.availabilityProbability(), 1e-9);
        assertEquals(predAt, a.predictedAt());
        assertEquals(4, a.availableBikes());
        assertEquals(stockAt, a.stockUpdatedAt());
        // 0.4 → 0, 확률 1-1.2 = -0.2 → 0으로 제한
        assertEquals(0, b.predictedBikes());
        assertEquals(0.0, b.availabilityProbability(), 1e-9);
    }

    @Test
    @DisplayName("예측 행이 없으면 UNAVAILABLE이고 값은 null(출처는 TABLE)")
    void predictionAbsent() {
        givenStations(station("A", CENTER_LAT, CENTER_LNG));
        when(bikeStockReader.find("A")).thenReturn(unavailableStock());
        when(predRepository.findByIdRentalIdInAndIdDowTypeAndIdTimeSlot(anyCollection(), any(), any()))
                .thenReturn(List.of());

        BikeStockOverviewItem item = service.overview(SW_LAT, SW_LNG, NE_LAT, NE_LNG, null, null).items().get(0);

        assertEquals(BikePredictionStatus.UNAVAILABLE, item.predictionStatus());
        assertEquals(OpsPredictionSource.TABLE, item.predictionSource());
        assertNull(item.predictedBikes());
        assertNull(item.availabilityProbability());
        assertNull(item.predictedAt());
    }

    @Test
    @DisplayName("arrivalTime이 없으면 Clock 현재 시각을 쓰고 Asia/Seoul 기준 슬롯을 조회한다")
    void defaultArrivalUsesClock() {
        givenStations(station("A", CENTER_LAT, CENTER_LNG));
        lenient().when(bikeStockReader.find(any())).thenReturn(unavailableStock());

        BikeStockOverviewResponse response = service.overview(SW_LAT, SW_LNG, NE_LAT, NE_LNG, null, null);

        assertEquals(NOW, response.arrivalTime().toInstant());
        assertEquals(NOW, response.generatedAt().toInstant());
        verify(predRepository).findByIdRentalIdInAndIdDowTypeAndIdTimeSlot(anyCollection(), eq(1), eq(24));
    }

    @Test
    @DisplayName("arrivalTime offset 시각은 같은 instant로 돌려주고 서울 시각으로 슬롯을 만든다")
    void explicitArrivalTime() {
        // 2026-10-04(일) 00:30 KST → dow_type 2, time_slot 1
        givenStations(station("A", CENTER_LAT, CENTER_LNG));
        lenient().when(bikeStockReader.find(any())).thenReturn(unavailableStock());

        BikeStockOverviewResponse response = service.overview(
                SW_LAT, SW_LNG, NE_LAT, NE_LNG, "2026-10-03T15:30:00Z", null);

        assertEquals(Instant.parse("2026-10-03T15:30:00Z"), response.arrivalTime().toInstant());
        verify(predRepository).findByIdRentalIdInAndIdDowTypeAndIdTimeSlot(anyCollection(), eq(2), eq(1));
    }

    private void givenStations(BikeStation... stations) {
        when(bikeStationRepository.findByLatBetweenAndLngBetween(any(), any(), any(), any()))
                .thenReturn(List.of(stations));
    }

    private void givenPreds(BikeStockPred... preds) {
        when(predRepository.findByIdRentalIdInAndIdDowTypeAndIdTimeSlot(anyCollection(), eq(1), eq(24)))
                .thenReturn(List.of(preds));
    }

    private static BikeStock unavailableStock() {
        return new BikeStock(null, null, null, BikeStockStatus.UNAVAILABLE);
    }

    private static BikeStation station(String rentalId, double lat, double lng) {
        BikeStation station = mock(BikeStation.class);
        lenient().when(station.getRentalId()).thenReturn(rentalId);
        lenient().when(station.getName()).thenReturn(rentalId + " 대여소");
        lenient().when(station.getLat()).thenReturn(lat);
        lenient().when(station.getLng()).thenReturn(lng);
        return station;
    }

    private static BikeStockPred pred(String rentalId, String expBikes, String pEmpty, OffsetDateTime updatedAt) {
        BikeStockPred pred = mock(BikeStockPred.class);
        lenient().when(pred.getId()).thenReturn(new BikeStockPredId(rentalId, 1, 24));
        lenient().when(pred.getExpBikes()).thenReturn(new BigDecimal(expBikes));
        lenient().when(pred.getPEmpty()).thenReturn(new BigDecimal(pEmpty));
        lenient().when(pred.getUpdatedAt()).thenReturn(updatedAt);
        return pred;
    }
}
