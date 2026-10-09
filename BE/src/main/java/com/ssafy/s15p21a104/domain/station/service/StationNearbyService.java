package com.ssafy.s15p21a104.domain.station.service;

import com.ssafy.s15p21a104.domain.station.dto.response.StationLineResponse;
import com.ssafy.s15p21a104.domain.station.dto.response.StationNearbyResponse;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import com.ssafy.s15p21a104.global.geo.GeoDistance;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** 좌표 기준 반경 안의 역을 거리순으로 찾고 소속 노선을 함께 돌려준다. 좌표·반경·개수 규칙은 따릉이 근처 조회와 같다. */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class StationNearbyService {

    static final int DEFAULT_RADIUS_METERS = 1000;
    static final int MAX_RADIUS_METERS = 3000;
    static final int DEFAULT_LIMIT = 20;
    static final int MAX_LIMIT = 50;
    private static final double METERS_PER_DEGREE_LAT = 111_320.0;

    private final StationRepository stationRepository;
    private final StationLineLookup stationLineLookup;

    public List<StationNearbyResponse> nearby(Double lat, Double lng, Integer radiusMeters, Integer limit) {
        validateCoordinate(lat, lng);
        int radius = resolveRadius(radiusMeters);
        int resolvedLimit = resolveLimit(limit);

        double latDelta = radius / METERS_PER_DEGREE_LAT;
        double lngDelta = radius / (METERS_PER_DEGREE_LAT * Math.cos(Math.toRadians(lat)));
        List<Station> candidates = stationRepository.findByLatBetweenAndLngBetween(
                lat - latDelta, lat + latDelta, lng - lngDelta, lng + lngDelta);

        record Hit(Station station, double distance) {
        }
        List<Hit> hits = candidates.stream()
                .filter(station -> station.getLat() != null && station.getLng() != null)
                .map(station -> new Hit(station,
                        GeoDistance.haversineMeters(lat, lng, station.getLat(), station.getLng())))
                .filter(hit -> hit.distance() <= radius)
                .sorted(Comparator.comparingDouble(Hit::distance))
                .limit(resolvedLimit)
                .toList();
        if (hits.isEmpty()) {
            return List.of();
        }

        Set<String> stationIds = hits.stream().map(hit -> hit.station().getStationId())
                .collect(Collectors.toSet());
        Map<String, Set<String>> lineIdsByStation = stationLineLookup.groupLineIdsByStation(stationIds);
        Map<String, String> lineNameById = stationLineLookup.lineNamesFor(lineIdsByStation);

        return hits.stream()
                .map(hit -> new StationNearbyResponse(
                        hit.station().getStationId(),
                        hit.station().getName(),
                        hit.station().getLat(),
                        hit.station().getLng(),
                        hit.distance(),
                        lineIdsByStation.getOrDefault(hit.station().getStationId(), Set.of()).stream()
                                .sorted()
                                .map(lineId -> new StationLineResponse(lineId, lineNameById.get(lineId)))
                                .toList()))
                .toList();
    }

    private void validateCoordinate(Double lat, Double lng) {
        if (lat == null || lng == null || lat < -90 || lat > 90 || lng < -180 || lng > 180) {
            throw new DomainException(ErrorType.INVALID_COORDINATE);
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
}
