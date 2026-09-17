package com.ssafy.s15p21a104.domain.bike.service;

import com.ssafy.s15p21a104.domain.bike.dto.response.BikeStationResponse;
import com.ssafy.s15p21a104.domain.bike.dto.response.BikeStockResponse;
import com.ssafy.s15p21a104.domain.bike.entity.BikeStation;
import com.ssafy.s15p21a104.domain.bike.repository.BikeStationRepository;
import com.ssafy.s15p21a104.domain.bike.stock.BikeStock;
import com.ssafy.s15p21a104.domain.bike.stock.BikeStockReader;
import com.ssafy.s15p21a104.global.geo.GeoDistance;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Comparator;
import java.util.List;

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
