package com.ssafy.s15p21a104.domain.station.service;

import com.ssafy.s15p21a104.domain.route.repository.RouteEdgeTimeRepository;
import com.ssafy.s15p21a104.domain.route.repository.RouteLineRepository;
import com.ssafy.s15p21a104.domain.station.dto.response.StationSearchResultResponse;
import com.ssafy.s15p21a104.domain.station.entity.Line;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Comparator;
import java.util.List;
import java.util.Locale;

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

        return ranked.stream()
                .flatMap(station -> toResults(station).stream())
                .limit(MAX_RESULTS)
                .toList();
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
    private List<StationSearchResultResponse> toResults(Station station) {
        List<String> lineIds = routeEdgeTimeRepository
                .findDistinctSubwayRouteIdsByStationId(station.getStationId());
        if (lineIds.isEmpty()) {
            return List.of(toResult(station, null, null));
        }
        return lineIds.stream()
                .sorted()
                .map(lineId -> toResult(station, lineId, lineName(lineId)))
                .toList();
    }

    private String lineName(String lineId) {
        return routeLineRepository.findById(lineId).map(Line::getName).orElse(null);
    }

    private StationSearchResultResponse toResult(Station station, String lineId, String lineName) {
        return new StationSearchResultResponse(
                station.getStationId(), station.getName(), lineId, lineName, station.getLat(), station.getLng());
    }
}
