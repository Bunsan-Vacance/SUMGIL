package com.ssafy.s15p21a104.domain.route.service;

import com.ssafy.s15p21a104.domain.route.dto.request.RoutePriority;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSearchResponse;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteSource;
import com.ssafy.s15p21a104.domain.route.dto.response.RouteType;
import com.ssafy.s15p21a104.domain.route.entity.TravelMode;
import com.ssafy.s15p21a104.domain.route.finder.FoundPath;
import com.ssafy.s15p21a104.domain.route.finder.RouteGraphRegistry;
import com.ssafy.s15p21a104.domain.route.finder.ShortestPathFinder;
import com.ssafy.s15p21a104.domain.route.graph.RouteGraph;
import com.ssafy.s15p21a104.domain.route.mapper.RouteMapper;
import com.ssafy.s15p21a104.domain.route.transfer.TransferRule;
import com.ssafy.s15p21a104.domain.station.entity.Station;
import com.ssafy.s15p21a104.domain.station.repository.StationRepository;
import com.ssafy.s15p21a104.global.exception.DomainException;
import com.ssafy.s15p21a104.global.exception.ErrorType;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;

/**
 * 경로 검색. 그래프 미적재 시 빈 배열(경로 없음)로 응답한다. 가짜 후보를 만들지 않는다.
 */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class RouteSearchService {

    private final StationRepository stationRepository;
    private final RouteGraphRegistry graphRegistry;
    private final TransferRule transferRule;

    public List<RouteSearchResponse> search(
            String originStationId,
            String destStationId,
            List<TravelMode> modes,
            RoutePriority priority
    ) {
        if (originStationId.equals(destStationId)) {
            throw new DomainException(ErrorType.SAME_ORIGIN_DEST);
        }

        // 그래프 미로드(미적재) 시 빈 배열(경로 없음)로 응답한다. 가짜 후보를 만들지 않는다.
        RouteGraph graph = graphRegistry == null ? null : graphRegistry.graph();
        if (graph == null) {
            return List.of();
        }

        findStation(originStationId);
        findStation(destStationId);
        return filterByModes(algorithmCandidates(graph, originStationId, destStationId), modes);
    }

    private List<RouteSearchResponse> algorithmCandidates(
            RouteGraph graph, String originStationId, String destStationId) {
        try {
            FoundPath found =
                    new ShortestPathFinder(transferRule).find(graph, originStationId, destStationId);
            List<RouteMapper.EngineSegment> segments = found.edges().stream()
                    .map(edge -> new RouteMapper.EngineSegment(
                            edge.fromNode(), edge.toNode(), edge.routeId(), edge.travelSec()))
                    .toList();
            Optional<RouteSearchResponse> response = RouteMapper.toResponse(
                    new RouteMapper.EnginePath(segments, found.totalSec(), found.transferCount()),
                    graphRegistry.stationInfos(), RouteType.SHORTEST, RouteSource.ALGORITHM);
            return response.map(List::of).orElseGet(List::of);
        } catch (DomainException exception) {
            if (exception.getErrorType() == ErrorType.ROUTE_NOT_FOUND) {
                return List.of();
            }
            throw exception;
        }
    }

    private Station findStation(String stationId) {
        return stationRepository.findById(stationId)
                .orElseThrow(() -> new DomainException(ErrorType.STATION_NOT_FOUND));
    }

    private List<RouteSearchResponse> filterByModes(List<RouteSearchResponse> candidates, List<TravelMode> modes) {
        if (modes == null || modes.isEmpty()) {
            return candidates;
        }
        return candidates.stream()
                .filter(candidate -> candidate.legs().stream()
                        .allMatch(leg -> isAlwaysAllowed(leg.mode()) || modes.contains(leg.mode())))
                .toList();
    }

    private boolean isAlwaysAllowed(TravelMode mode) {
        return mode == TravelMode.WALK || mode == TravelMode.TRANSFER;
    }
}
