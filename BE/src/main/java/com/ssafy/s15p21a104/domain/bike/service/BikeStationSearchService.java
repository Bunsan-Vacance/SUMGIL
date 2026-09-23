package com.ssafy.s15p21a104.domain.bike.service;

import com.ssafy.s15p21a104.domain.bike.dto.response.BikeStationResponse;
import com.ssafy.s15p21a104.domain.bike.dto.response.BikeStockResponse;
import com.ssafy.s15p21a104.domain.bike.dto.response.BikePredictionResponse;
import com.ssafy.s15p21a104.domain.bike.dto.response.BikePredictionSource;
import com.ssafy.s15p21a104.domain.bike.dto.response.BikePredictionStatus;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStation;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPred;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStockPredId;
import com.ssafy.s15p21a104.domain.bike.eta.BikeEtaReader;
import com.ssafy.s15p21a104.domain.bike.eta.BikeEtaStock;
import com.ssafy.s15p21a104.domain.bike.repository.BikeStationRepository;
import com.ssafy.s15p21a104.domain.bike.repository.BikeStockPredRepository;
import com.ssafy.s15p21a104.domain.bike.stock.BikeStock;
import com.ssafy.s15p21a104.domain.bike.stock.BikeStockReader;
import com.ssafy.s15p21a104.domain.route.dto.request.DepartureSlot;
import com.ssafy.s15p21a104.global.geo.GeoDistance;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeParseException;
import java.util.Comparator;
import java.util.List;
import java.util.Optional;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class BikeStationSearchService {

    private static final int DEFAULT_RADIUS_METERS = 500;
    private static final int MAX_RADIUS_METERS = 3000;
    private static final int DEFAULT_LIMIT = 20;
    private static final int MAX_LIMIT = 100;

    private final BikeStationRepository bikeStationRepository;
    private final BikeStockReader bikeStockReader;
    private final BikeStockPredRepository bikeStockPredRepository;
    private final BikeEtaReader bikeEtaReader;

    public List<BikeStationResponse> nearby(Double lat, Double lng, Integer radiusMeters, Integer limit) {
        validateCoordinate(lat, lng);
        int radius = resolveRadius(radiusMeters);
        int resolvedLimit = resolveLimit(limit);

        double latDelta = radius / 111_320.0;
        double lngDelta = radius / (111_320.0 * Math.cos(Math.toRadians(lat)));

        List<BikeStation> candidates = bikeStationRepository.findByLatBetweenAndLngBetween(
                lat - latDelta, lat + latDelta, lng - lngDelta, lng + lngDelta);

        return candidates.stream()
                .map(station -> toResponse(station,
                        GeoDistance.haversineMeters(lat, lng, station.getLat(), station.getLng())))
                .filter(response -> response.distanceMeters() <= radius)
                .sorted(Comparator.comparing(BikeStationResponse::distanceMeters))
                .limit(resolvedLimit)
                .toList();
    }

    /** 등록된 대여소지만 실시간 재고 캐시가 없거나(만료 포함) 값이 깨졌으면 UNAVAILABLE로 다룬다(에러 아님). */
    public BikeStockResponse stock(String rentalId) {
        BikeStation station = bikeStationRepository.findById(rentalId)
                .orElseThrow(() -> new DomainException(ErrorType.BIKE_STATION_NOT_FOUND));
        BikeStock stock = bikeStockReader.find(station.getRentalId());
        return new BikeStockResponse(station.getRentalId(), stock.available(), stock.updatedAt(), stock.status());
    }

    /**
     * 도착 시각 기준 예상 재고(S15P21A104-237, FE-BE 통합 계약 §6).
     * 도착까지 30분 이내면 AI 실시간 모델({@code eta-stock}, v4-weather-final LightGBM)을 먼저 쓰고 — 이때 {@code source}
     * 는 MODEL, {@code predictedAt} 은 부른 시각이다 — 못 쓰면 정적 예측표({@code bike_stock_pred})로 떨어진다
     * (S15P21A104-309, 판정은 {@link BikeEtaReader}). 실시간 수집값(Redis)은 여기서 직접 읽지 않는다.
     *
     * @param rentalId 대여소 ID
     * @param arrivalTime 도착 예상 시각(offset ISO). 없거나 깨지면 400
     * @return 예측 응답. 행이 없으면 UNAVAILABLE(값을 0으로 바꾸지 않음)
     */
    public BikePredictionResponse prediction(String rentalId, String arrivalTime) {
        BikeStation station = bikeStationRepository.findById(rentalId)
                .orElseThrow(() -> new DomainException(ErrorType.BIKE_STATION_NOT_FOUND));
        OffsetDateTime arrival = parseArrival(arrivalTime);
        // AI 실시간 모델(eta-stock)을 먼저 본다(309). 못 쓰면(30분 초과·호출 실패 등) 빈 값이고 아래 평균표 조회가 그대로 돈다.
        Optional<BikeEtaStock> model = bikeEtaReader.find(station.getRentalId(), arrival);
        if (model.isPresent()) {
            BikeEtaStock eta = model.get();
            return new BikePredictionResponse(BikePredictionStatus.AVAILABLE, eta.predictedBikes(),
                    eta.availabilityProbability(), eta.predictedAt(), arrival, station.getRentalId(),
                    BikePredictionSource.MODEL);
        }
        // 슬롯 규칙은 탐색과 같은 정의(DepartureSlot)를 쓴다 — pred 테이블 키와 일치해야 한다.
        LocalDateTime seoul = arrival.atZoneSameInstant(ZoneId.of("Asia/Seoul")).toLocalDateTime();
        DepartureSlot slot = DepartureSlot.of(seoul);
        Optional<BikeStockPred> row = bikeStockPredRepository.findById(
                new BikeStockPredId(station.getRentalId(), slot.dowType(), slot.timeSlot()));
        if (row.isEmpty()) {
            return new BikePredictionResponse(BikePredictionStatus.UNAVAILABLE, null, null, null,
                    arrival, station.getRentalId(), BikePredictionSource.MOCK);
        }
        BikeStockPred pred = row.get();
        int bikes = pred.getExpBikes().setScale(0, RoundingMode.HALF_UP).intValueExact();
        double probability =
                Math.min(1.0, Math.max(0.0, 1.0 - pred.getPEmpty().doubleValue()));
        BikePredictionSource source = "model".equalsIgnoreCase(pred.getSource())
                ? BikePredictionSource.MODEL : BikePredictionSource.MOCK;
        return new BikePredictionResponse(BikePredictionStatus.AVAILABLE, bikes, probability,
                pred.getUpdatedAt(), arrival, station.getRentalId(), source);
    }

    private OffsetDateTime parseArrival(String arrivalTime) {
        if (arrivalTime == null || arrivalTime.isBlank()) {
            throw new DomainException(ErrorType.BAD_REQUEST);
        }
        try {
            return OffsetDateTime.parse(arrivalTime);
        } catch (DateTimeParseException e) {
            throw new DomainException(ErrorType.BAD_REQUEST);
        }
    }

    private void validateCoordinate(Double lat, Double lng) {
        if (lat < -90 || lat > 90 || lng < -180 || lng > 180) {
            throw new DomainException(ErrorType.BAD_REQUEST);
        }
    }

    private int resolveRadius(Integer radiusMeters) {
        if (radiusMeters == null) {
            return DEFAULT_RADIUS_METERS;
        }
        if (radiusMeters <= 0 || radiusMeters > MAX_RADIUS_METERS) {
            throw new DomainException(ErrorType.BAD_REQUEST);
        }
        return radiusMeters;
    }

    private int resolveLimit(Integer limit) {
        if (limit == null) {
            return DEFAULT_LIMIT;
        }
        if (limit <= 0 || limit > MAX_LIMIT) {
            throw new DomainException(ErrorType.BAD_REQUEST);
        }
        return limit;
    }

    private BikeStationResponse toResponse(BikeStation station, double distanceMeters) {
        BikeStock stock = bikeStockReader.find(station.getRentalId());
        return new BikeStationResponse(
                station.getRentalId(),
                station.getName(),
                station.getLat(),
                station.getLng(),
                station.getDockCount(),
                distanceMeters,
                stock.available(),
                stock.updatedAt()
        );
    }
}
