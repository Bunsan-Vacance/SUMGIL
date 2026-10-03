package com.ssafy.s15p21a104.domain.ops.service;

import com.ssafy.s15p21a104.domain.bike.dto.response.BikePredictionStatus;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStation;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPred;
import com.ssafy.s15p21a104.domain.bike.repository.BikeStationRepository;
import com.ssafy.s15p21a104.domain.bike.stock.BikeStock;
import com.ssafy.s15p21a104.domain.bike.stock.BikeStockReader;
import com.ssafy.s15p21a104.domain.ops.dto.response.BikeStockOverviewItem;
import com.ssafy.s15p21a104.domain.ops.dto.response.BikeStockOverviewResponse;
import com.ssafy.s15p21a104.domain.ops.dto.response.OpsPredictionSource;
import com.ssafy.s15p21a104.domain.ops.repository.OpsBikeStockPredRepository;
import com.ssafy.s15p21a104.domain.route.dto.request.DepartureSlot;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import com.ssafy.s15p21a104.global.geo.GeoDistance;
import java.math.RoundingMode;
import java.time.Clock;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeParseException;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 운영자 뷰용 대여소 재고·예측 일괄 조회. 읽기 전용(PG·Redis)이다.
 * 예측은 {@code bike_stock_pred} 표만 읽고 AI 모델은 부르지 않으므로 {@link OpsPredictionSource#TABLE} 고정이다.
 */
@Service
@Transactional(readOnly = true)
public class OpsBikeStockService {

    private static final ZoneId SEOUL = ZoneId.of("Asia/Seoul");
    private static final int DEFAULT_LIMIT = 200;
    private static final int MAX_LIMIT = 500;

    private final BikeStationRepository bikeStationRepository;
    private final BikeStockReader bikeStockReader;
    private final OpsBikeStockPredRepository predRepository;
    private final Clock clock;

    /**
     * 운영 생성자. 앱에는 프로파일별(collect·consume)로만 Clock 빈이 있어 타입 주입이 모호해질 수 있으므로
     * 여기서는 시스템 시계를 직접 쓰고, 테스트는 아래 Clock 받는 생성자를 쓴다.
     */
    @Autowired
    public OpsBikeStockService(BikeStationRepository bikeStationRepository, BikeStockReader bikeStockReader,
                               OpsBikeStockPredRepository predRepository) {
        this(bikeStationRepository, bikeStockReader, predRepository, Clock.system(SEOUL));
    }

    OpsBikeStockService(BikeStationRepository bikeStationRepository, BikeStockReader bikeStockReader,
                        OpsBikeStockPredRepository predRepository, Clock clock) {
        this.bikeStationRepository = bikeStationRepository;
        this.bikeStockReader = bikeStockReader;
        this.predRepository = predRepository;
        this.clock = clock;
    }

    public BikeStockOverviewResponse overview(Double swLat, Double swLng, Double neLat, Double neLng,
                                              String arrivalTime, Integer limit) {
        validateBbox(swLat, swLng, neLat, neLng);
        int resolvedLimit = resolveLimit(limit);
        OffsetDateTime arrival = resolveArrival(arrivalTime);
        DepartureSlot slot = DepartureSlot.of(arrival.atZoneSameInstant(SEOUL).toLocalDateTime());

        double centerLat = (swLat + neLat) / 2;
        double centerLng = (swLng + neLng) / 2;
        List<BikeStation> sorted = bikeStationRepository.findByLatBetweenAndLngBetween(swLat, neLat, swLng, neLng)
                .stream()
                .sorted(Comparator.comparingDouble(
                        s -> GeoDistance.haversineMeters(centerLat, centerLng, s.getLat(), s.getLng())))
                .toList();
        boolean truncated = sorted.size() > resolvedLimit;
        List<BikeStation> stations = truncated ? sorted.subList(0, resolvedLimit) : sorted;

        Map<String, BikeStockPred> predByRental = new HashMap<>();
        if (!stations.isEmpty()) {
            List<String> ids = stations.stream().map(BikeStation::getRentalId).toList();
            for (BikeStockPred pred : predRepository.findByIdRentalIdInAndIdDowTypeAndIdTimeSlot(
                    ids, slot.dowType(), slot.timeSlot())) {
                predByRental.put(pred.getId().getRentalId(), pred);
            }
        }

        List<BikeStockOverviewItem> items = stations.stream()
                .map(s -> toItem(s, bikeStockReader.find(s.getRentalId()), predByRental.get(s.getRentalId())))
                .toList();
        return new BikeStockOverviewResponse(arrival, items.size(), truncated, OffsetDateTime.now(clock), items);
    }

    private BikeStockOverviewItem toItem(BikeStation station, BikeStock stock, BikeStockPred pred) {
        Integer predictedBikes = null;
        Double probability = null;
        OffsetDateTime predictedAt = null;
        BikePredictionStatus status = BikePredictionStatus.UNAVAILABLE;
        if (pred != null) {
            status = BikePredictionStatus.AVAILABLE;
            predictedBikes = pred.getExpBikes().setScale(0, RoundingMode.HALF_UP).intValueExact();
            probability = Math.min(1.0, Math.max(0.0, 1.0 - pred.getPEmpty().doubleValue()));
            predictedAt = pred.getUpdatedAt();
        }
        return new BikeStockOverviewItem(station.getRentalId(), station.getName(), station.getLat(),
                station.getLng(), stock.rackCount(), stock.available(), stock.status(), stock.updatedAt(),
                predictedBikes, probability, status, OpsPredictionSource.TABLE, predictedAt);
    }

    private OffsetDateTime resolveArrival(String arrivalTime) {
        if (arrivalTime == null || arrivalTime.isBlank()) {
            return OffsetDateTime.now(clock);
        }
        try {
            return OffsetDateTime.parse(arrivalTime);
        } catch (DateTimeParseException e) {
            throw new DomainException(ErrorType.BAD_REQUEST);
        }
    }

    private void validateBbox(Double swLat, Double swLng, Double neLat, Double neLng) {
        if (swLat == null || swLng == null || neLat == null || neLng == null
                || !validLat(swLat) || !validLat(neLat) || !validLng(swLng) || !validLng(neLng)
                || swLat >= neLat || swLng >= neLng) {
            throw new DomainException(ErrorType.BAD_REQUEST);
        }
    }

    private boolean validLat(double v) {
        return !Double.isNaN(v) && v >= -90 && v <= 90;
    }

    private boolean validLng(double v) {
        return !Double.isNaN(v) && v >= -180 && v <= 180;
    }

    private int resolveLimit(Integer limit) {
        if (limit == null) {
            return DEFAULT_LIMIT;
        }
        if (limit < 1 || limit > MAX_LIMIT) {
            throw new DomainException(ErrorType.BAD_REQUEST);
        }
        return limit;
    }
}
