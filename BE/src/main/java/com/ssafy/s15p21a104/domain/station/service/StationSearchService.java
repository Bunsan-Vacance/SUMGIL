package com.ssafy.s15p21a104.domain.station.service;

import com.ssafy.s15p21a104.domain.route.repository.RouteEdgeTimeRepository;
import com.ssafy.s15p21a104.domain.route.repository.RouteLineRepository;
import com.ssafy.s15p21a104.domain.route.repository.StationRouteEdge;
import com.ssafy.s15p21a104.domain.station.dto.response.StationSearchResultResponse;
import com.ssafy.s15p21a104.domain.station.entity.Line;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.stream.Collectors;

/**
 * 역 이름으로 BE 정식 역 ID(station_id, 역번호)를 찾는다. FE가 Kakao 검색 결과를 임의로 정규화해
 * routes/search에 넘기던 방식을 대체한다(S15P21A104-63 확장, FE 제안 — 계약 미승인).
 */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class StationSearchService {

    private static final int MAX_RESULTS = 20;

    private final StationRepository stationRepository;
    private final RouteEdgeTimeRepository routeEdgeTimeRepository;
    private final RouteLineRepository routeLineRepository;

    public List<StationSearchResultResponse> search(String query) {
        String normalized = normalize(query);
        if (normalized.isEmpty()) {
            return List.of();
        }

        List<Station> ranked = stationRepository.findByNameContainingIgnoreCase(normalized).stream()
                .sorted(Comparator.comparingInt((Station station) -> rank(station.getName(), normalized))
                        .thenComparing(Station::getName))
                .toList();
        if (ranked.isEmpty()) {
            return List.of();
        }

        Set<String> stationIds = ranked.stream().map(Station::getStationId).collect(Collectors.toSet());
        Map<String, Set<String>> lineIdsByStation = groupLineIdsByStation(stationIds);
        Map<String, String> lineNameById = lineNamesFor(lineIdsByStation);

        return ranked.stream()
                .flatMap(station -> toResults(station, lineIdsByStation.get(station.getStationId()), lineNameById)
                        .stream())
                .limit(MAX_RESULTS)
                .toList();
    }

    /** 매칭된 역 전체의 소속 노선을 쿼리 한 번으로 묶어 온다(역마다 따로 조회하는 N+1 방지). */
    private Map<String, Set<String>> groupLineIdsByStation(Set<String> stationIds) {
        Map<String, Set<String>> result = new HashMap<>();
        for (StationRouteEdge edge : routeEdgeTimeRepository.findSubwayRouteEdgesTouchingStations(stationIds)) {
            if (stationIds.contains(edge.fromNode())) {
                result.computeIfAbsent(edge.fromNode(), key -> new TreeSet<>()).add(edge.routeId());
            }
            if (stationIds.contains(edge.toNode())) {
                result.computeIfAbsent(edge.toNode(), key -> new TreeSet<>()).add(edge.routeId());
            }
        }
        return result;
    }

    /** 등장한 노선 ID 전체의 이름을 쿼리 한 번으로 묶어 온다. */
    private Map<String, String> lineNamesFor(Map<String, Set<String>> lineIdsByStation) {
        Set<String> allLineIds = lineIdsByStation.values().stream()
                .flatMap(Set::stream)
                .collect(Collectors.toSet());
        if (allLineIds.isEmpty()) {
            return Map.of();
        }
        return routeLineRepository.findAllById(allLineIds).stream()
                .collect(Collectors.toMap(Line::getLineId, Line::getName));
    }

    /** 앞뒤 공백 제거, 끝의 "역" 표기 허용(예: "강변역" -> "강변"). */
    private String normalize(String query) {
        if (query == null) {
            return "";
        }
        String trimmed = query.strip();
        if (trimmed.length() > 1 && trimmed.endsWith("역")) {
            trimmed = trimmed.substring(0, trimmed.length() - 1);
        }
        return trimmed;
    }

    /** 정확 일치(0) > 접두 일치(1) > 부분 일치(2). */
    private int rank(String name, String query) {
        String lowerName = name.toLowerCase(Locale.ROOT);
        String lowerQuery = query.toLowerCase(Locale.ROOT);
        if (lowerName.equals(lowerQuery)) {
            return 0;
        }
        if (lowerName.startsWith(lowerQuery)) {
            return 1;
        }
        return 2;
    }

    /** 환승역은 소속 노선 수만큼 행을 나눈다. 노선 정보가 없으면(그래프 미포함) 행 1개, lineId/lineName은 null. */
    private List<StationSearchResultResponse> toResults(
            Station station, Set<String> lineIds, Map<String, String> lineNameById) {
        if (lineIds == null || lineIds.isEmpty()) {
            return List.of(toResult(station, null, null));
        }
        return lineIds.stream()
                .map(lineId -> toResult(station, lineId, lineNameById.get(lineId)))
                .toList();
    }

    private StationSearchResultResponse toResult(Station station, String lineId, String lineName) {
        return new StationSearchResultResponse(
                station.getStationId(), station.getName(), lineId, lineName, station.getLat(), station.getLng());
    }
}
